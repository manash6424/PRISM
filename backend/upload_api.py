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