import uuid
import os
import re
import json
import traceback
import numpy as np
import pandas as pd
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from groq import Groq

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# In-memory store: session_id -> {filename, columns, preview, df}
_upload_store = {}


class QueryBody(BaseModel):
    natural_language: str


def read_excel_smart(filepath):
    """Auto-detect real header row in Excel files with merged/multi headers"""
    raw = pd.read_excel(filepath, header=None)
    header_row = 0
    for i, row in raw.iterrows():
        row_str = ' '.join([str(v).lower() for v in row.values])
        if any(keyword in row_str for keyword in ['s.no', 'prn', 'student name', 'name', 'roll', 'id', 'title']):
            header_row = i
            break
    df = pd.read_excel(filepath, header=header_row)
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


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename.endswith(('.csv', '.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

    try:
        contents = await file.read()
        session_id = str(uuid.uuid4())
        filepath = os.path.join(UPLOAD_DIR, f"{session_id}_{file.filename}")

        with open(filepath, "wb") as f:
            f.write(contents)

        if file.filename.endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            df = read_excel_smart(filepath)

        df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

        _upload_store[session_id] = {
            "filename": file.filename,
            "filepath": filepath,
            "columns": list(df.columns),
            "row_count": len(df),
            "df": df
        }

        preview = df.head(5).fillna('').to_dict(orient='records')

        return {
            "success": True,
            "session_id": session_id,
            "filename": file.filename,
            "columns": list(df.columns),
            "row_count": len(df),
            "preview": preview
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/{session_id}/query")
async def query_upload(session_id: str, body: QueryBody):
    if session_id not in _upload_store:
        raise HTTPException(status_code=404, detail="Upload session not found")

    natural_language = body.natural_language.strip()
    if not natural_language:
        raise HTTPException(status_code=400, detail="Query is required")

    store = _upload_store[session_id]
    df = store["df"]

    col_info = ", ".join([f"{c} ({df[c].dtype})" for c in df.columns])
    sample = df.head(3).fillna('').to_dict(orient='records')

    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set in environment")

    client = Groq(api_key=groq_key)

    prompt = f"""You are a pandas data analyst. The user has a DataFrame named 'df' with these columns: {col_info}
Sample data: {json.dumps(sample)}
User question: {natural_language}

Rules:
1. Return ONLY a single pandas expression. No markdown, no explanation, no comments.
2. The variable is always 'df'.
3. For string filters, ALWAYS use na=False: df[df['col'].str.lower().str.contains('value', na=False)]
4. When searching for a name or text, use the correct column from the sample data above.
5. Always return full rows as DataFrame, never select a single column with ['col'] at the end.
6. Use double brackets [['col1','col2']] if you need specific columns.

Examples:
- df[df['student_name'].str.lower().str.contains('john', na=False)]
- df[df['student_name'].str.lower().str.contains('john', na=False)][['student_name','presentation_topic']]
- df.groupby('campaign')['clicks'].sum().reset_index()
- df.sort_values('revenue', ascending=False).head(10)"""

    pandas_code = ""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.1
        )
        pandas_code = response.choices[0].message.content.strip()
        pandas_code = pandas_code.replace("```python", "").replace("```", "").strip()

        pandas_code = sanitize_pandas_code(pandas_code)

        result_df = eval(pandas_code, {"df": df, "pd": pd, "np": np})

        if isinstance(result_df, pd.Series):
            result_df = result_df.reset_index()
        if not isinstance(result_df, pd.DataFrame):
            result_df = pd.DataFrame({"result": [result_df]})

        result_df = result_df.fillna('')
        columns = list(result_df.columns)
        results = result_df.head(1000).to_dict(orient='records')
        total_count = len(result_df)

        # ✅ Generate natural language answer with correct count
        natural_answer = ""
        try:
            answer_prompt = f"""The user asked: "{natural_language}"
Total rows found: {total_count}
Sample of data result: {json.dumps(results[:20])}

IMPORTANT RULES:
- For count/how many questions, ALWAYS use the "Total rows found" number: {total_count}
- Never count the sample data yourself, always use {total_count} as the count
- Give a short, direct, friendly answer in 1-2 sentences
- No code, no markdown, no bullet points
- Just a plain human answer

Examples:
- "There are 73 students who did not upload their presentation topic."
- "Manash Mandal's presentation topic is Context Free Grammar (CFG)."
- "The top student by marks is John Doe with 95 marks."
If no data found, say so clearly."""

            answer_response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": answer_prompt}],
                max_tokens=150,
                temperature=0.1
            )
            natural_answer = answer_response.choices[0].message.content.strip()
        except Exception:
            natural_answer = ""

        return {
            "success": True,
            "columns": columns,
            "results": results,
            "row_count": total_count,
            "generated_code": pandas_code,
            "filename": store["filename"],
            "answer": natural_answer
        }

    except Exception as e:
        print("FULL ERROR:", traceback.format_exc())
        return {
            "success": False,
            "error": str(e),
            "generated_code": pandas_code
        }


@router.delete("/upload/{session_id}")
async def delete_upload(session_id: str):
    if session_id not in _upload_store:
        raise HTTPException(status_code=404, detail="Session not found")
    store = _upload_store.pop(session_id)
    try:
        os.remove(store["filepath"])
    except Exception:
        pass
    return {"success": True}


def get_upload_store():
    return _upload_store


# ─────────────────────────────────────────────────────────────────────────────
# NEW: Marketing KPIs endpoint — added below, zero changes to code above
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/upload/{session_id}/marketing-kpis")
async def marketing_kpis(session_id: str):
    if session_id not in _upload_store:
        raise HTTPException(status_code=404, detail="Session not found")

    df = _upload_store[session_id]["df"].copy()
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

    roas = round(total_revenue / total_spend, 2)                          if total_spend > 0       else 0
    ctr  = round((total_clicks / total_impressions) * 100, 2)             if total_impressions > 0 else 0
    cpc  = round(total_spend / total_clicks, 2)                           if total_clicks > 0      else 0
    cpa  = round(total_spend / total_conversions, 2)                      if total_conversions > 0 else 0

    # Campaign breakdown
    campaigns = []
    if campaign_col:
        agg_map = {k: v for k, v in {
            'spend':       spend_col,
            'impressions': impressions_col,
            'clicks':      clicks_col,
            'conversions': conversions_col,
            'revenue':     revenue_col
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

    # Daily spend trend
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
            "roas": roas,
            "ctr":  ctr,
            "cpc":  cpc,
            "cpa":  cpa
        },
        "campaigns":   campaigns[:10],
        "daily_spend": daily,
        "detected_columns": {
            "spend":       spend_col,
            "impressions": impressions_col,
            "clicks":      clicks_col,
            "revenue":     revenue_col,
            "campaign":    campaign_col
        }
    }