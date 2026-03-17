"""
API routes for PRISM.
"""

import uuid
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from ..models.database import (
    DatabaseConnection,
    ConnectionStatus,
    QueryRequest,
    QueryResponse,
    ExportRequest,
    ExportFormat,
)
from ..services.database_manager import db_manager
from ..services.schema_discovery import schema_discovery
from ..services.query_executor import query_executor
from ..services.export_service import export_service
from ..config import get_settings
from ..utils.validators import (
    validate_connection_config,
    validate_natural_language_query,
    validate_sql_filename,
)

router = APIRouter()
settings = get_settings()


class RawSQLRequest(BaseModel):
    connection_id: str
    sql: str


# ==================== Database Connection Endpoints ====================

@router.post("/connections", response_model=dict)
async def create_connection(connection: DatabaseConnection):
    is_valid, error = validate_connection_config(
        connection.host,
        connection.port,
        connection.database,
        connection.username,
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    connection.id = str(uuid.uuid4())

    success, message = await db_manager.test_connection(connection)
    if not success:
        connection.status = ConnectionStatus.ERROR
        raise HTTPException(status_code=400, detail=f"Connection failed: {message}")

    connected = await db_manager.connect(connection)
    if not connected:
        raise HTTPException(status_code=400, detail="Failed to establish connection")

    connection.status = ConnectionStatus.CONNECTED
    connection.last_connected_at = datetime.now(timezone.utc)

    db_manager._save_connections()
    schema_discovery.clear_cache(connection.id)

    return {
        "id": connection.id,
        "name": connection.name,
        "status": connection.status.value,
        "message": "Connection successful",
    }


@router.get("/connections", response_model=List[dict])
async def list_connections():
    connections = []
    for conn_id, conn in db_manager._connection_cache.items():
        connections.append({
            "id": conn_id,
            "name": conn.name,
            "dialect": conn.dialect.value,
            "host": conn.host,
            "database": conn.database,
            "status": conn.status.value,
        })
    return connections


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str):
    conn = db_manager._connection_cache.get(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    success, message = await db_manager.test_connection(conn)

    return {
        "success": success,
        "message": message,
        "status": "connected" if success else "error",
    }


# ==================== Schema Endpoints ====================

@router.get("/connections/{connection_id}/schema")
async def get_schema(connection_id: str, force_refresh: bool = False):
    conn = db_manager._connection_cache.get(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        schema_data = await schema_discovery.discover_full_schema(
            connection_id, force_refresh=force_refresh
        )

        tables = []
        for table in schema_data.get("tables", []):
            tables.append({
                "name": table.get("name", ""),
                "columns": [
                    {
                        "name": col.get("name", ""),
                        "data_type": col.get("data_type", "text"),
                        "is_nullable": col.get("is_nullable", True),
                        "is_primary_key": col.get("is_primary_key", False),
                    }
                    for col in table.get("columns", [])
                ],
                "row_count": table.get("row_count", 0),
            })

        return {"tables": tables, "connection_id": connection_id}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connections/{connection_id}", response_model=dict)
async def get_connection(connection_id: str):
    conn = db_manager._connection_cache.get(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    return {
        "id": conn.id,
        "name": conn.name,
        "dialect": conn.dialect.value,
        "host": conn.host,
        "port": conn.port,
        "database": conn.database,
        "username": conn.username,
        "status": conn.status.value,
        "created_at": conn.created_at.isoformat(),
        "last_connected_at": conn.last_connected_at.isoformat()
        if conn.last_connected_at else None,
    }


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str):
    success = await db_manager.disconnect(connection_id)
    if not success:
        raise HTTPException(status_code=404, detail="Connection not found")

    schema_discovery.clear_cache(connection_id)
    return {"message": "Connection deleted successfully"}


# ==================== Query Endpoints ====================

@router.post("/query", response_model=QueryResponse)
async def execute_natural_language_query(request: QueryRequest):
    conn = db_manager._connection_cache.get(request.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    if request.connection_id not in db_manager._sessions:
        connected = await db_manager.connect(conn)
        if not connected:
            raise HTTPException(status_code=400, detail="Failed to reconnect to database")

    is_valid, error = validate_natural_language_query(request.natural_language)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    try:
        response = await query_executor.execute(request)

        if not response.success:
            raise HTTPException(
                status_code=400,
                detail=f"Query execution failed: {response.error_message}"
            )

        return response

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/raw", response_model=QueryResponse)
async def execute_raw_sql(request: RawSQLRequest):
    conn = db_manager._connection_cache.get(request.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    response = await query_executor.execute_raw_sql(
        request.connection_id,
        request.sql,
    )

    if not response.success:
        raise HTTPException(
            status_code=400,
            detail=f"Query execution failed: {response.error_message}"
        )

    return response


@router.get("/query/history")
async def get_query_history(limit: int = 50):
    return {
        "history": [
            q.model_dump() for q in query_executor.get_query_history(limit=limit)
        ]
    }


@router.get("/query/{query_id}")
async def get_query_result(query_id: str):
    query = query_executor.get_query_by_id(query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")

    return query.model_dump()


# ==================== Export Endpoints ====================

@router.post("/export")
async def create_export(request: ExportRequest):
    query = query_executor.get_query_by_id(request.query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")

    if request.filename:
        is_valid, error = validate_sql_filename(request.filename)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error)

    try:
        filepath = await export_service.export(request, query)

        return {
            "success": True,
            "filepath": filepath,
            "filename": request.filename or f"export_{request.query_id[:8]}",
            "format": request.format.value,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== System Endpoints ====================

@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.app_version,
    }


@router.get("/info")
async def get_system_info():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "debug": settings.debug,
        "ai_provider": settings.ai.provider,
        "ai_model": settings.ai.model,
    }


# ==================== Auth Endpoints ====================

class ForgotPasswordRequest(BaseModel):
    email: str


@router.post("/auth/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    try:
        import os
        from supabase import create_client
        supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_ANON_KEY")
        )
        supabase.auth.reset_password_email(request.email)
        return {"success": True, "message": "Reset link sent"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    # ==================== AI Suggestions Endpoint ====================

class SuggestionsRequest(BaseModel):
    input: str

@router.post("/suggestions")
async def get_suggestions(request: SuggestionsRequest):
    try:
        import httpx
        import os
        import json
        
        api_key = os.getenv("AI_API_KEY")
        base_url = os.getenv("AI_BASE_URL")
        model = os.getenv("AI_MODEL")
        
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{
                        "role": "user",
                        "content": f'Give 3 short database query suggestions completing: "{request.input}". Reply ONLY with a JSON array of 3 strings, nothing else.'
                    }],
                    "max_tokens": 200
                },
                timeout=10.0
            )
            data = res.json()
            text = data["choices"][0]["message"]["content"].strip()
            suggestions = json.loads(text)
            return {"suggestions": suggestions}
    except Exception as e:
        return {"suggestions": []}
















