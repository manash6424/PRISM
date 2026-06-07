import uuid
import os
import re
import json
import traceback
import numpy as np
import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from groq import Groq

# ── NEW IMPORT (added for KPI Excel report) ───────────────────────────────────
try:
    from backend.services.kpi_report_generator import generate_kpi_excel
except ModuleNotFoundError:
    from services.kpi_report_generator import generate_kpi_excel

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# In-memory store: session_id -> {files: [...], merged_df: df, file_schemas: [...]}
_upload_store = {}


class QueryBody(BaseModel):
    natural_language: str


def read_excel_smart(filepath):
    """
    Auto-detect real header row in Excel files with merged/multi-row headers.

    Handles files like university attendance reports that have:
      Row 0: "Sandlp University — Nashik School of Science..."
      Row 1: "Student Attendance Report — DBE"
      Row 2: "FYB.SC — Semester II — Division A — 12th Jan..."
      Row 3: S.No. | PRN. | Student Name | ...   ← actual header
      Row 4+: data

    Strategy:
    1. Scan up to first 15 rows for the actual header row
    2. A row is a header if it contains a known identifier keyword AND
       has at least 3 non-null, non-numeric values (real column names)
    3. If no header found, default to row 0
    4. After reading, drop any fully-empty rows/columns
    """
    raw = pd.read_excel(filepath, header=None)

    HEADER_KEYWORDS = [
        's.no', 'sr.no', 'sr no', 'prn', 'prn.', 'roll', 'roll no',
        'student name', 'student_name', 'name', 'id', 'title',
        'emp', 'employee', 'reg no', 'enrollment',
        # marketing keywords too
        'campaign', 'date', 'spend', 'clicks', 'impressions',
    ]

    header_row = 0
    for i, row in raw.head(15).iterrows():
        values      = [str(v).strip() for v in row.values if str(v).strip() not in ('', 'nan', 'NaN', 'None')]
        row_str     = ' '.join(values).lower()
        has_keyword = any(kw in row_str for kw in HEADER_KEYWORDS)
        # Must have keyword AND enough non-numeric values to look like a real header
        non_numeric = sum(1 for v in values if not v.replace('.', '').replace('-', '').isnumeric())
        if has_keyword and non_numeric >= 2:
            header_row = i
            break

    df = pd.read_excel(filepath, header=header_row)

    # Drop columns that are entirely unnamed (Unnamed: X artifacts from merged cells)
    df = df.loc[:, ~df.columns.astype(str).str.match(r'^Unnamed')]

    # Drop fully empty rows
    df = df.dropna(how='all').reset_index(drop=True)

    return df


def sanitize_pandas_code(code: str) -> str:
    """Auto-fix str.contains() calls to handle NaN values"""
    code = re.sub(
        r"str\.contains\(([^)]+)\)",
        lambda m: (
            f"str.contains({m.group(1)}, na=False)"
            if "na=" not in m.group(1)
            else m.group(0)
        ),
        code
    )
    return code


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names"""
    df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]
    return df


# ── Student/entity identity columns — if ANY of these overlap, files share a population ──
_IDENTITY_KEYS = {'prn', 'roll', 'roll_no', 'rollno', 's.no', 'sno', 'enrollment',
                  'student_id', 'emp_id', 'employee_id', 'id', 'reg_no', 'registration'}


def detect_merge_mode(existing_df: pd.DataFrame, new_df: pd.DataFrame):
    """
    Decide how to combine two dataframes.

    Returns one of three modes:
      'stack'   — same schema, stack rows (e.g. two sections of the same report)
      'join'    — same students/entities, different columns → merge on shared key
                  (e.g. attendance file + marks file for the same class)
      'concat'  — truly different schemas, put side by side
    """
    existing_cols = set(c for c in existing_df.columns if c != '_source_file')
    new_cols      = set(c for c in new_df.columns      if c != '_source_file')
    overlap       = existing_cols & new_cols
    overlap_ratio = len(overlap) / max(len(existing_cols), len(new_cols))

    # Check if they share an identity/key column (PRN, roll no, student_id …)
    shared_identity = overlap & _IDENTITY_KEYS

    if overlap_ratio >= 0.80:
        return 'stack', None
    elif shared_identity:
        # Use the best available key (prefer prn > roll_no > id > first match)
        key_priority = ['prn', 'roll_no', 'rollno', 'roll', 'student_id', 'id',
                        'emp_id', 'employee_id', 'enrollment', 'reg_no', 's.no', 'sno']
        join_key = next((k for k in key_priority if k in shared_identity), next(iter(shared_identity)))
        return 'join', join_key
    else:
        return 'concat', None


def merge_dataframes(existing_df: pd.DataFrame, new_df: pd.DataFrame, new_filename: str) -> pd.DataFrame:
    """
    Three-way smart merge:

    STACK  — identical schema → stack rows, tag with _source_file
    JOIN   — same students/entities, different columns → pd.merge on shared key
             (this is the fix for: attendance.xlsx + marks.xlsx for same 100 students
              → result is 100 rows with ALL columns, not 200 stacked or 100 side-by-side)
    CONCAT — different schemas → side-by-side with suffixes on colliding columns
    """
    existing_cols = set(c for c in existing_df.columns if c != '_source_file')
    new_cols      = set(c for c in new_df.columns      if c != '_source_file')
    overlap       = existing_cols & new_cols

    mode, join_key = detect_merge_mode(existing_df, new_df)

    if mode == 'stack':
        # ── Same schema: stack rows ──────────────────────────────────────
        if '_source_file' in existing_df.columns:
            existing_nums = existing_df['_source_file'].dropna().unique()
            max_num = max(
                (int(str(t).replace('file_', '')) for t in existing_nums if str(t).startswith('file_')),
                default=0
            )
            new_file_num = max_num + 1
        else:
            existing_df = existing_df.copy()
            existing_df['_source_file'] = 'file_1'
            new_file_num = 2

        new_df = new_df.copy()
        new_df['_source_file'] = f'file_{new_file_num}'

        # Fill missing columns with '' so no NaN confuses the AI
        all_cols = set(existing_df.columns) | set(new_df.columns)
        for col in all_cols:
            if col not in existing_df.columns:
                existing_df[col] = ''
            if col not in new_df.columns:
                new_df[col] = ''

        merged = pd.concat([existing_df, new_df], ignore_index=True)

    elif mode == 'join':
        # ── Same population, different columns: merge on shared key ─────
        # Suffix non-key colliding columns so nothing is silently lost
        colliding_non_key = (overlap - {join_key})
        rename_map = {col: col + '_file2' for col in colliding_non_key}
        new_df = new_df.copy().rename(columns=rename_map)

        merged = pd.merge(
            existing_df,
            new_df,
            on=join_key,
            how='outer',        # keep all students even if one file has extras
            suffixes=('', '_file2')
        )
        merged = merged.fillna('')

    else:
        # ── Truly different schemas: side-by-side ─────────────────────
        base_suffix = '_' + os.path.splitext(new_filename)[0][:10].replace(' ', '_')
        colliding   = overlap
        rename_map  = {col: col + base_suffix for col in colliding}
        new_df      = new_df.copy().rename(columns=rename_map)

        merged = pd.concat(
            [existing_df.reset_index(drop=True), new_df.reset_index(drop=True)],
            axis=1
        )

    return merged, mode  # return mode so caller can log merge_strategy correctly


def build_schema_context(store: dict) -> str:
    """
    Build a rich schema string for the AI prompt covering all three merge modes:

    STACK mode   → _source_file column exists; tell AI per-file row ranges
    JOIN mode    → files were merged on a key; df has ALL columns, N unique entities
    CONCAT mode  → side-by-side; each file's columns have suffixes; total rows = max(file rows)

    This is the key fix for "queries only see one file" and wrong counts.
    """
    lines       = []
    merged_df   = store["merged_df"]
    total_rows  = len(merged_df)
    all_cols    = merged_df.columns.tolist()

    # Per-file individual counts (ground truth, never changes)
    per_file_counts = {f['filename']: f['row_count'] for f in store["files"]}
    individual_total = sum(per_file_counts.values())

    lines.append(f"MERGED DATAFRAME 'df': {total_rows} rows, {len(all_cols)} columns")
    lines.append(f"All columns: {', '.join(all_cols)}")
    lines.append(f"Individual file row counts (GROUND TRUTH for count questions):")
    for fname, cnt in per_file_counts.items():
        lines.append(f"  • '{fname}': {cnt} rows")
    lines.append(f"  → Combined unique students/entities: {total_rows} rows in df")
    lines.append(f"  → Sum across all files: {individual_total} rows total")
    lines.append("")

    if '_source_file' in merged_df.columns:
        # STACK mode
        lines.append("MERGE MODE: rows stacked (same schema, different sections/batches)")
        lines.append("Use df[df['_source_file'] == 'file_N'] to filter by specific file.")
        lines.append("")
        lines.append("FILES IN 'df':")
        for f in store["files"]:
            tag      = f.get("source_tag", "")
            file_rows = merged_df[merged_df['_source_file'] == tag] if tag else merged_df
            lines.append(f"  • {tag} → '{f['filename']}': {len(file_rows)} rows")
            lines.append(f"    Columns: {', '.join(f['columns'])}")
            sample = file_rows.head(2).fillna('').to_dict(orient='records')
            lines.append(f"    Sample: {json.dumps(sample)}")
    else:
        if len(store["files"]) == 1:
            lines.append("MERGE MODE: single file")
        else:
            # Could be JOIN or CONCAT — explain both clearly
            lines.append("MERGE MODE: files merged into one table (entity-join or column-join)")
            lines.append("The df already has all columns from all files in a single table.")
            lines.append("DO NOT filter by file — just query df directly for any student/entity.")
            lines.append("")
            lines.append("FILES MERGED:")
            for f in store["files"]:
                lines.append(f"  • '{f['filename']}': originally {f['row_count']} rows")
                lines.append(f"    Original columns: {', '.join(f['columns'])}")

        sample = merged_df.head(3).fillna('').to_dict(orient='records')
        lines.append(f"Sample rows from merged df: {json.dumps(sample)}")

    return '\n'.join(lines)


@router.post("/upload/session/new")
async def create_session():
    """Create a new empty multi-file session"""
    session_id = str(uuid.uuid4())
    _upload_store[session_id] = {
        "files": [],
        "merged_df": None,
    }
    return {"success": True, "session_id": session_id}


@router.post("/upload/session/{session_id}/add")
async def add_file_to_session(session_id: str, file: UploadFile = File(...)):
    """Add a file to an existing session, merging with existing data"""

    if not file.filename.endswith(('.csv', '.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

    if session_id not in _upload_store:
        _upload_store[session_id] = {"files": [], "merged_df": None}

    try:
        contents = await file.read()
        file_id  = str(uuid.uuid4())
        filepath = os.path.join(UPLOAD_DIR, f"{file_id}_{file.filename}")

        with open(filepath, "wb") as f:
            f.write(contents)

        if file.filename.endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            df = read_excel_smart(filepath)

        df = clean_columns(df)
        df = df.dropna(axis=1, how='all')

        # Guard: if header detection failed and df is empty, fall back to header=0
        if len(df) == 0 or len(df.columns) == 0:
            df = pd.read_excel(filepath, header=0) if not file.filename.endswith('.csv') else pd.read_csv(filepath)
            df = clean_columns(df)
            df = df.dropna(axis=1, how='all')

        actual_row_count = len(df)

        store = _upload_store[session_id]

        # Determine the source tag this file will get BEFORE merging
        # so we can store it in file_info for schema context later
        if store["merged_df"] is not None:
            existing_has_source = '_source_file' in store["merged_df"].columns
            if existing_has_source:
                existing_nums = store["merged_df"]['_source_file'].dropna().unique()
                max_num = max(
                    (int(str(t).replace('file_', '')) for t in existing_nums if str(t).startswith('file_')),
                    default=0
                )
                source_tag = f'file_{max_num + 1}'
            else:
                source_tag = 'file_2'  # existing will become file_1, new becomes file_2
        else:
            source_tag = 'file_1'

        # Merge with existing data if any
        if store["merged_df"] is not None:
            merged_df, merge_mode = merge_dataframes(store["merged_df"].copy(), df.copy(), file.filename)
        else:
            merged_df  = df
            merge_mode = 'single'

        # ── Detect merge strategy for the badge ──────────────────────────
        if merge_mode == 'stack':
            merge_strategy = 'rows_stacked'
        elif merge_mode == 'join':
            merge_strategy = 'entity_joined'
        elif merge_mode == 'concat':
            merge_strategy = 'columns_joined'
        else:
            merge_strategy = 'single'

        file_info = {
            "file_id":    file_id,
            "filename":   file.filename,
            "filepath":   filepath,
            "columns":    list(df.columns),
            "row_count":  actual_row_count,   # always correct after cleaning
            "source_tag": source_tag,
        }
        store["files"].append(file_info)
        store["merged_df"] = merged_df

        # Fix source_tag for file_1 if it wasn't set (first file uploaded)
        if len(store["files"]) == 1:
            store["files"][0]["source_tag"] = "file_1"

        preview = merged_df.head(5).fillna('').to_dict(orient='records')

        return {
            "success":        True,
            "session_id":     session_id,
            "file_id":        file_id,
            "filename":       file.filename,
            "files":          store["files"],
            "columns":        list(merged_df.columns),
            "row_count":      len(merged_df),
            "preview":        preview,
            "merge_strategy": merge_strategy,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/upload/session/{session_id}/file/{file_id}")
async def remove_file_from_session(session_id: str, file_id: str):
    """Remove a specific file from session and recompute merged df"""
    if session_id not in _upload_store:
        raise HTTPException(status_code=404, detail="Session not found")

    store = _upload_store[session_id]
    file_to_remove = next((f for f in store["files"] if f["file_id"] == file_id), None)

    if not file_to_remove:
        raise HTTPException(status_code=404, detail="File not found in session")

    try:
        os.remove(file_to_remove["filepath"])
    except Exception:
        pass

    store["files"] = [f for f in store["files"] if f["file_id"] != file_id]

    if not store["files"]:
        store["merged_df"] = None
        return {"success": True, "files": [], "columns": [], "row_count": 0, "preview": []}

    # Re-read and re-merge all remaining files
    merged_df = None
    for idx, f in enumerate(store["files"]):
        if f["filename"].endswith('.csv'):
            df = pd.read_csv(f["filepath"])
        else:
            df = read_excel_smart(f["filepath"])
        df = clean_columns(df)

        if merged_df is None:
            merged_df = df
            f["source_tag"] = "file_1"
        else:
            # Determine what tag this becomes after re-merge
            if '_source_file' in merged_df.columns:
                existing_nums = merged_df['_source_file'].dropna().unique()
                max_num = max(
                    (int(str(t).replace('file_', '')) for t in existing_nums if str(t).startswith('file_')),
                    default=0
                )
                f["source_tag"] = f'file_{max_num + 1}'
            else:
                f["source_tag"] = 'file_2'
            merged_df, _ = merge_dataframes(merged_df, df, f["filename"])

    store["merged_df"] = merged_df
    preview = merged_df.head(5).fillna('').to_dict(orient='records')

    return {
        "success":   True,
        "files":     store["files"],
        "columns":   list(merged_df.columns),
        "row_count": len(merged_df),
        "preview":   preview,
    }


@router.post("/upload/session/{session_id}/query")
async def query_session(session_id: str, body: QueryBody):
    """Query the merged dataframe for a session"""
    if session_id not in _upload_store:
        raise HTTPException(status_code=404, detail="Session not found")

    store = _upload_store[session_id]
    if store["merged_df"] is None:
        raise HTTPException(status_code=400, detail="No files uploaded in this session")

    natural_language = body.natural_language.strip()
    if not natural_language:
        raise HTTPException(status_code=400, detail="Query is required")

    df             = store["merged_df"]
    df_total_rows  = len(df)
    col_info       = ", ".join([f"{c} ({df[c].dtype})" for c in df.columns])
    filenames      = [f["filename"] for f in store["files"]]
    file_counts    = ", ".join([f"{f['filename']} ({f['row_count']} rows, tag={f.get('source_tag','?')})" for f in store["files"]])

    # ── CORE FIX: Rich schema context instead of 3 generic sample rows ────
    schema_context = build_schema_context(store)

    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set in environment")

    client = Groq(api_key=groq_key)

    # Per-file individual counts — ground truth for count questions
    per_file_counts     = {f['filename']: f['row_count'] for f in store["files"]}
    individual_total    = sum(per_file_counts.values())
    per_file_counts_str = ", ".join([f"'{k}': {v} rows" for k, v in per_file_counts.items()])
    has_source_col      = '_source_file' in df.columns

    prompt = f"""You are a pandas data analyst. The user has a merged DataFrame named 'df'.

{schema_context}

Column types: {col_info}
User question: {natural_language}

CRITICAL RULES:
1. Return ONLY a single pandas expression — no markdown, no comments, no explanation.
2. The variable is always 'df'. Do not reassign df.
3. For string filters, ALWAYS use na=False: df[df['col'].str.lower().str.contains('value', na=False)]
4. Always return a DataFrame. Use [['col']] for single-column results, .reset_index() after aggregations.
5. NEVER use len(), .shape, or any scalar-returning expression.
6. For count/total questions, return the relevant DataFrame — the system counts rows for you.
7. For aggregations (sum, avg, group by), always end with .reset_index().
8. Do NOT filter out '' values — they are legitimate placeholders for missing cross-file data.

COUNT / "HOW MANY" RULES (VERY IMPORTANT):
- Individual file row counts (ground truth): {per_file_counts_str}
- Total across ALL files: {individual_total} rows
- If asked "how many students in BOTH files" or "total students" or "students from both files":
  {'→ Return df (all rows in merged df), do NOT filter by _source_file' if not has_source_col else '→ Return df (all rows = sum of both files)'}
- If asked about a SPECIFIC file by name, filter: df[df['_source_file'] == 'file_N']
  (only valid if _source_file column exists: {has_source_col})
- The merged df already correctly represents all students — do not try to "add up" files manually.

MERGE MODE CONTEXT:
{'_source_file column EXISTS — files are stacked as rows. Use _source_file to filter by file.' if has_source_col else 'NO _source_file column — files are merged into ONE table. All students are already in df. Just query df directly.'}

Good expression examples:
- "total students from both files"    → df
- "students in file 1"                → df[df['_source_file'] == 'file_1']  (only if _source_file exists)
- "total spend by campaign"           → df.groupby('campaign')['spend'].sum().reset_index()
- "top 10 by marks"                   → df.sort_values('marks', ascending=False).head(10)
- "students named john"               → df[df['student_name'].str.lower().str.contains('john', na=False)]
- "average marks per section"         → df.groupby('section')['marks'].mean().reset_index()
- "students who passed (marks >= 40)" → df[df['marks'] >= 40]"""

    # ── PYTHON-SIDE INTENT DETECTOR ───────────────────────────────────────────
    def _is_count_question(q: str) -> bool:
        q = q.lower()
        count_words  = {'total', 'how many', 'count', 'number of', 'how much'}
        entity_words = {'student', 'record', 'row', 'entry', 'data', 'person',
                        'employee', 'staff', 'teacher', 'user', 'customer'}
        has_count  = any(c in q for c in count_words)
        has_entity = any(e in q for e in entity_words)
        return has_count and has_entity

    def _find_best_name_col(df: pd.DataFrame, files: list) -> str | None:
        """Pick the cleanest student-name column (prefer unsuffixed)."""
        candidates = [c for c in df.columns
                      if any(k in c.lower() for k in ['student_name', 'name', 'student'])]
        # Prefer columns that DON'T have a suffix (i.e. no _file2 / _CD_CIA etc.)
        clean = [c for c in candidates if not any(
            c.endswith(s) for s in ['_file2', '_file1', '_file3']
        )]
        return (clean or candidates or [None])[0]

    pandas_code = ""
    try:
        # ── Short-circuit for pure count/total questions ──────────────────
        if _is_count_question(natural_language):
            pandas_code = "df"
            raw_result  = df

        else:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.1,
            )
            pandas_code = response.choices[0].message.content.strip()
            pandas_code = pandas_code.replace("```python", "").replace("```", "").strip()
            pandas_code = sanitize_pandas_code(pandas_code)

            raw_result = eval(pandas_code, {"df": df, "pd": pd, "np": np})

        # ── Post-process: if LLM still only returned suffixed columns,
        #    fall back to full df so at least the count is right ──────────
        if isinstance(raw_result, pd.DataFrame):
            if len(raw_result.columns) > 0 and all(
                any(col.endswith(s) for s in ['_file2', '_file1', '_file3', '_CD_CIA', '_fy_att'])
                for col in raw_result.columns
            ):
                pandas_code = "df  # auto-corrected: LLM returned single-file columns"
                raw_result  = df

        # ── Handle scalar results ──────────────────────────────────────────
        scalar_value = None
        if isinstance(raw_result, (int, float, np.integer, np.floating)):
            scalar_value = int(raw_result) if isinstance(raw_result, (int, np.integer)) else float(raw_result)
            result_df    = pd.DataFrame({"result": [scalar_value]})
        elif isinstance(raw_result, pd.Series):
            result_df = raw_result.reset_index()
        elif isinstance(raw_result, pd.DataFrame):
            result_df = raw_result
        else:
            result_df = pd.DataFrame({"result": [str(raw_result)]})

        result_df   = result_df.fillna('')
        columns     = list(result_df.columns)
        results     = result_df.head(1000).to_dict(orient='records')
        total_count = len(result_df)

        # ── Natural language answer ────────────────────────────────────────
        is_count_q = _is_count_question(natural_language)
        natural_answer = ""
        try:
            if is_count_q:
                natural_answer = (
                    f"There are {individual_total} students in total across "
                    f"{len(store['files'])} file(s): "
                    + ", ".join([f"'{f['filename']}' ({f['row_count']} students)"
                                 for f in store["files"]]) + "."
                )
            else:
                if scalar_value is not None:
                    answer_context = f"The computed result is exactly: {scalar_value}"
                else:
                    answer_context = (
                        f"The query returned {total_count} rows.\n"
                        f"Sample of results (up to 10): {json.dumps(results[:10])}"
                    )

                answer_prompt = f"""The user asked: "{natural_language}"
Files: {per_file_counts_str}
Total rows in merged df: {df_total_rows}
Query result rows: {total_count}
{answer_context}

Give a SHORT, direct, friendly answer in 1-2 sentences.
Use EXACT numbers from the context — never guess. No code, no markdown."""

                ans_response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": answer_prompt}],
                    max_tokens=150,
                    temperature=0.1,
                )
                natural_answer = ans_response.choices[0].message.content.strip()
        except Exception:
            natural_answer = ""

        return {
            "success":        True,
            "columns":        columns,
            "results":        results,
            "row_count":      total_count,
            "generated_code": pandas_code,
            "filenames":      filenames,
            "answer":         natural_answer,
        }

    except Exception as e:
        print("FULL ERROR:", traceback.format_exc())
        return {
            "success":        False,
            "error":          str(e),
            "generated_code": pandas_code,
        }


@router.get("/upload/session/{session_id}/marketing-kpis")
async def marketing_kpis(session_id: str):
    if session_id not in _upload_store:
        raise HTTPException(status_code=404, detail="Session not found")

    store = _upload_store[session_id]
    if store["merged_df"] is None:
        raise HTTPException(status_code=400, detail="No files in session")

    df   = store["merged_df"].copy()
    cols = list(df.columns)

    def find_col(keywords):
        for k in keywords:
            for c in cols:
                if k in c.lower():
                    return c
        return None

    spend_col       = find_col(['spend', 'cost', 'amount', 'budget'])
    impressions_col = find_col(['impression', 'impr'])
    clicks_col      = find_col(['click'])
    conversions_col = find_col(['conversion', 'result', 'purchase'])
    revenue_col     = find_col(['revenue', 'value', 'sales'])
    campaign_col    = find_col(['campaign', 'ad_set', 'adset', 'ad'])
    date_col        = find_col(['date', 'day'])

    def safe_sum(col):
        if col and col in df.columns:
            return float(pd.to_numeric(df[col], errors='coerce').fillna(0).sum())
        return 0.0

    total_spend       = safe_sum(spend_col)
    total_impressions = safe_sum(impressions_col)
    total_clicks      = safe_sum(clicks_col)
    total_conversions = safe_sum(conversions_col)
    total_revenue     = safe_sum(revenue_col)

    roas = round(total_revenue / total_spend, 2)              if total_spend > 0       else 0
    ctr  = round((total_clicks / total_impressions) * 100, 2) if total_impressions > 0 else 0
    cpc  = round(total_spend / total_clicks, 2)               if total_clicks > 0      else 0
    cpa  = round(total_spend / total_conversions, 2)          if total_conversions > 0 else 0

    campaigns = []
    if campaign_col:
        agg_map = {k: v for k, v in {
            'spend':       spend_col,
            'impressions': impressions_col,
            'clicks':      clicks_col,
            'conversions': conversions_col,
            'revenue':     revenue_col,
        }.items() if v}

        for col in agg_map.values():
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        grouped = df.groupby(campaign_col)[list(agg_map.values())].sum().reset_index()
        grouped.columns = [campaign_col] + list(agg_map.keys())

        for _, row in grouped.iterrows():
            sp = float(row.get('spend', 0))
            rv = float(row.get('revenue', 0))
            cl = float(row.get('clicks', 0))
            im = float(row.get('impressions', 0))
            campaigns.append({
                "name":        str(row[campaign_col]),
                "spend":       round(sp, 2),
                "impressions": int(im),
                "clicks":      int(cl),
                "conversions": int(row.get('conversions', 0)),
                "revenue":     round(rv, 2),
                "roas":        round(rv / sp, 2) if sp > 0 else 0,
                "ctr":         round((cl / im) * 100, 2) if im > 0 else 0,
            })
        campaigns.sort(key=lambda x: x['spend'], reverse=True)

    daily = []
    if date_col and spend_col:
        df['_date'] = pd.to_datetime(df[date_col], errors='coerce')
        ds = df.groupby('_date')[spend_col].sum().reset_index()
        ds = ds.dropna(subset=['_date']).sort_values('_date')
        daily = [
            {"date": str(r['_date'])[:10], "spend": round(float(r[spend_col]), 2)}
            for _, r in ds.iterrows()
        ]

    return {
        "success": True,
        "kpis": {
            "total_spend":       round(total_spend, 2),
            "total_impressions": int(total_impressions),
            "total_clicks":      int(total_clicks),
            "total_conversions": int(total_conversions),
            "total_revenue":     round(total_revenue, 2),
            "roas": roas, "ctr": ctr, "cpc": cpc, "cpa": cpa,
        },
        "campaigns":   campaigns[:10],
        "daily_spend": daily,
        "detected_columns": {
            "spend":       spend_col,
            "impressions": impressions_col,
            "clicks":      clicks_col,
            "revenue":     revenue_col,
            "campaign":    campaign_col,
        },
    }


@router.delete("/upload/session/{session_id}")
async def delete_session(session_id: str):
    """Delete entire session and all its files"""
    if session_id not in _upload_store:
        raise HTTPException(status_code=404, detail="Session not found")

    store = _upload_store.pop(session_id)
    for f in store.get("files", []):
        try:
            os.remove(f["filepath"])
        except Exception:
            pass

    return {"success": True}


# ── Legacy single-file endpoints (kept for backwards compatibility) ──────────

@router.post("/upload")
async def upload_file_legacy(file: UploadFile = File(...)):
    session_id = str(uuid.uuid4())
    _upload_store[session_id] = {"files": [], "merged_df": None}

    if not file.filename.endswith(('.csv', '.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

    try:
        contents = await file.read()
        file_id  = str(uuid.uuid4())
        filepath = os.path.join(UPLOAD_DIR, f"{file_id}_{file.filename}")

        with open(filepath, "wb") as f:
            f.write(contents)

        if file.filename.endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            df = read_excel_smart(filepath)

        df = clean_columns(df)

        file_info = {
            "file_id":    file_id,
            "filename":   file.filename,
            "filepath":   filepath,
            "columns":    list(df.columns),
            "row_count":  len(df),
            "source_tag": "file_1",
        }
        _upload_store[session_id]["files"].append(file_info)
        _upload_store[session_id]["merged_df"] = df

        preview = df.head(5).fillna('').to_dict(orient='records')

        return {
            "success":    True,
            "session_id": session_id,
            "filename":   file.filename,
            "columns":    list(df.columns),
            "row_count":  len(df),
            "preview":    preview,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/{session_id}/query")
async def query_upload_legacy(session_id: str, body: QueryBody):
    return await query_session(session_id, body)


@router.delete("/upload/{session_id}")
async def delete_upload_legacy(session_id: str):
    return await delete_session(session_id)


@router.get("/upload/{session_id}/marketing-kpis")
async def marketing_kpis_legacy(session_id: str):
    return await marketing_kpis(session_id)


def get_upload_store():
    return _upload_store


# ══════════════════════════════════════════════════════════════════════════════
# NEW ENDPOINT — KPI Excel Report Download
# Added below all existing code — nothing above this line was changed.
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/upload/kpi-report/{session_id}")
async def download_kpi_report(session_id: str, request: Request):
    """
    Generate and stream a white-label KPI Excel report for a session.

    Reads KPI data directly from the session's merged DataFrame so the
    frontend does NOT need to pass raw numbers — it only needs to send
    optional branding fields.

    Optional JSON body:
    {
        "client_name":  "Zomato",
        "agency_name":  "MediaPulse Agency",
        "date_range":   "1 Apr – 30 Apr 2025"
    }
    """
    if session_id not in _upload_store:
        raise HTTPException(status_code=404, detail="Session not found")

    store = _upload_store[session_id]
    if store["merged_df"] is None:
        raise HTTPException(status_code=400, detail="No files in session")

    # ── Parse optional branding from request body ─────────────────────────
    try:
        body = await request.json()
    except Exception:
        body = {}

    client_name = body.get("client_name", "Client")
    agency_name = body.get("agency_name", "Your Agency")
    date_range  = body.get("date_range",  "")

    # ── Re-use existing marketing_kpis logic to compute KPIs ─────────────
    df   = store["merged_df"].copy()
    cols = list(df.columns)

    def find_col(keywords):
        for k in keywords:
            for c in cols:
                if k in c.lower():
                    return c
        return None

    spend_col       = find_col(['spend', 'cost', 'amount', 'budget'])
    impressions_col = find_col(['impression', 'impr'])
    clicks_col      = find_col(['click'])
    conversions_col = find_col(['conversion', 'result', 'purchase'])
    revenue_col     = find_col(['revenue', 'value', 'sales'])
    campaign_col    = find_col(['campaign', 'ad_set', 'adset', 'ad'])
    date_col        = find_col(['date', 'day'])

    def safe_sum(col):
        if col and col in df.columns:
            return float(pd.to_numeric(df[col], errors='coerce').fillna(0).sum())
        return 0.0

    total_spend       = safe_sum(spend_col)
    total_impressions = safe_sum(impressions_col)
    total_clicks      = safe_sum(clicks_col)
    total_conversions = safe_sum(conversions_col)
    total_revenue     = safe_sum(revenue_col)

    roas = round(total_revenue / total_spend, 2)              if total_spend > 0       else 0
    ctr  = round((total_clicks / total_impressions) * 100, 2) if total_impressions > 0 else 0
    cpc  = round(total_spend / total_clicks, 2)               if total_clicks > 0      else 0
    cpa  = round(total_spend / total_conversions, 2)          if total_conversions > 0 else 0

    kpi_data = {
        "roas":        roas,
        "ctr":         ctr,
        "total_spend": round(total_spend, 2),
        "impressions": int(total_impressions),
        "clicks":      int(total_clicks),
        "cpc":         cpc,
        "conversions": int(total_conversions),
        "cpa":         cpa,
    }

    # ── Build campaign rows ───────────────────────────────────────────────
    campaign_rows = []
    if campaign_col:
        agg_map = {k: v for k, v in {
            'spend':       spend_col,
            'impressions': impressions_col,
            'clicks':      clicks_col,
            'conversions': conversions_col,
            'revenue':     revenue_col,
        }.items() if v}

        for col in agg_map.values():
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        grouped = df.groupby(campaign_col)[list(agg_map.values())].sum().reset_index()
        grouped.columns = [campaign_col] + list(agg_map.keys())

        for _, row in grouped.iterrows():
            sp = float(row.get('spend', 0))
            rv = float(row.get('revenue', 0))
            cl = float(row.get('clicks', 0))
            im = float(row.get('impressions', 0))
            campaign_rows.append({
                "campaign":    str(row[campaign_col]),
                "spend":       round(sp, 2),
                "impressions": int(im),
                "clicks":      int(cl),
                "conversions": int(row.get('conversions', 0)),
                "roas":        round(rv / sp, 2) if sp > 0 else 0,
                "ctr":         round((cl / im) * 100, 2) if im > 0 else 0,
                "cpc":         round(sp / cl, 2) if cl > 0 else 0,
            })
        campaign_rows.sort(key=lambda x: x['spend'], reverse=True)

    # ── Build daily rows ──────────────────────────────────────────────────
    daily_rows = []
    if date_col and spend_col:
        df['_date'] = pd.to_datetime(df[date_col], errors='coerce')

        agg_cols = {spend_col: 'spend'}
        if revenue_col:
            agg_cols[revenue_col] = 'revenue'

        ds = df.groupby('_date')[[spend_col] + ([revenue_col] if revenue_col else [])].sum().reset_index()
        ds = ds.dropna(subset=['_date']).sort_values('_date')

        for _, row in ds.iterrows():
            sp = float(row[spend_col])
            rv = float(row[revenue_col]) if revenue_col else 0
            daily_rows.append({
                "date":  str(row['_date'])[:10],
                "spend": round(sp, 2),
                "roas":  round(rv / sp, 2) if sp > 0 else 0,
            })

    # ── Generate Excel bytes ──────────────────────────────────────────────
    try:
        excel_bytes = generate_kpi_excel(
            kpi_data      = kpi_data,
            campaign_rows = campaign_rows,
            daily_rows    = daily_rows,
            client_name   = client_name,
            agency_name   = agency_name,
            date_range    = date_range,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Excel generation failed: {str(e)}")

    from datetime import datetime as _dt
    safe_client = client_name.replace(' ', '_')
    filename    = f"KPI_Report_{safe_client}_{_dt.now().strftime('%Y%m%d')}.xlsx"

    return Response(
        content    = excel_bytes,
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers    = {"Content-Disposition": f"attachment; filename={filename}"},
    )