"""
API routes for AI Desktop Copilot.
"""

import uuid
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
from ..services.report_generator import report_generator
from ..services.alert_service import alert_service, AlertChannel
from ..config import get_settings
from ..utils.validators import (
    validate_connection_config,
    validate_natural_language_query,
    validate_sql_filename,
)

router = APIRouter()
settings = get_settings()


# ==================== Helper Models ====================

class RawSQLRequest(BaseModel):
    connection_id: str
    sql: str


# ==================== Database Connection Endpoints ====================

@router.post("/connections", response_model=dict)
async def create_connection(connection: DatabaseConnection):
    """Create a new database connection."""

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

    await db_manager.connect(connection)
    connection.status = ConnectionStatus.CONNECTED
    connection.last_connected_at = datetime.now(timezone.utc)

    schema_discovery.clear_cache(connection.id)

    return {
        "id": connection.id,
        "name": connection.name,
        "status": connection.status.value,
        "message": "Connection successful",
    }


@router.get("/connections", response_model=List[dict])
async def list_connections():
    """List all database connections."""

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


@router.get("/connections/{connection_id}", response_model=dict)
async def get_connection(connection_id: str):
    """Get connection details."""

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
    """Delete a database connection."""

    success = await db_manager.disconnect(connection_id)
    if not success:
        raise HTTPException(status_code=404, detail="Connection not found")

    schema_discovery.clear_cache(connection_id)
    return {"message": "Connection deleted successfully"}


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str):
    """Test database connection."""

    conn = db_manager._connection_cache.get(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    success, message = await db_manager.test_connection(conn)

    return {
        "success": success,
        "message": message,
        "status": "connected" if success else "error",
    }


# ==================== Query Endpoints ====================

@router.post("/query", response_model=QueryResponse)
async def execute_natural_language_query(request: QueryRequest):
    """Execute a natural language query."""

    conn = db_manager._connection_cache.get(request.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/raw", response_model=QueryResponse)
async def execute_raw_sql(request: RawSQLRequest):
    """Execute raw SQL query."""

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
            "filename": request.filename
            or f"export_{request.query_id[:8]}",
            "format": request.format.value,
        }

    except Exception as e:
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