"""
API routes for PRISM.
All endpoints protected with user authentication.
"""

import uuid
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
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
from ..services.alert_service import alert_service
from ..services.report_generator import report_generator
from ..config import get_settings
from ..utils.validators import (
    validate_connection_config,
    validate_natural_language_query,
    validate_sql_filename,
)
from ..api.auth import get_current_user

router = APIRouter()
settings = get_settings()


class RawSQLRequest(BaseModel):
    connection_id: str
    sql: str


# ==================== Database Connection Endpoints ====================

@router.post("/connections", response_model=dict)
async def create_connection(
    connection: DatabaseConnection,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["id"]
    user_token = current_user.get("token")

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

    connected = await db_manager.connect(connection, user_id=user_id, user_token=user_token)
    if not connected:
        raise HTTPException(status_code=400, detail="Failed to establish connection")

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
async def list_connections(
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["id"]
    user_token = current_user.get("token")

    await db_manager.load_connections_for_user(user_id, user_token)

    user_connections = db_manager.get_user_connections(user_id)

    connections = []
    for conn_id, conn in user_connections.items():
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
async def test_connection(
    connection_id: str,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["id"]

    if not db_manager.is_connection_owned_by_user(connection_id, user_id):
        raise HTTPException(status_code=403, detail="Access denied")

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
async def get_schema(
    connection_id: str,
    force_refresh: bool = False,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["id"]

    if not db_manager.is_connection_owned_by_user(connection_id, user_id):
        raise HTTPException(status_code=403, detail="Access denied")

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
async def get_connection(
    connection_id: str,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["id"]

    if not db_manager.is_connection_owned_by_user(connection_id, user_id):
        raise HTTPException(status_code=403, detail="Access denied")

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
async def delete_connection(
    connection_id: str,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["id"]

    if not db_manager.is_connection_owned_by_user(connection_id, user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    success = await db_manager.disconnect(connection_id)
    if not success:
        raise HTTPException(status_code=404, detail="Connection not found")

    schema_discovery.clear_cache(connection_id)
    return {"message": "Connection deleted successfully"}


# ==================== Query Endpoints ====================

@router.post("/query", response_model=QueryResponse)
async def execute_natural_language_query(
    request: QueryRequest,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["id"]
    user_token = current_user.get("token")

    if not db_manager.is_connection_owned_by_user(request.connection_id, user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    conn = db_manager._connection_cache.get(request.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    if request.connection_id not in db_manager._sessions:
        connected = await db_manager.connect(conn, user_id=user_id, user_token=user_token)
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
async def execute_raw_sql(
    request: RawSQLRequest,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["id"]

    if not db_manager.is_connection_owned_by_user(request.connection_id, user_id):
        raise HTTPException(status_code=403, detail="Access denied")

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
async def get_query_history(
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    return {
        "history": [
            q.model_dump() for q in query_executor.get_query_history(limit=limit)
        ]
    }


@router.get("/query/{query_id}")
async def get_query_result(
    query_id: str,
    current_user: dict = Depends(get_current_user)
):
    query = query_executor.get_query_by_id(query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")

    return query.model_dump()


# ==================== Export Endpoints ====================

@router.post("/export")
async def create_export(
    request: ExportRequest,
    current_user: dict = Depends(get_current_user)
):
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
async def get_suggestions(
    request: SuggestionsRequest,
    current_user: dict = Depends(get_current_user)
):
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


# ==================== Alert Endpoints ====================

class AlertCreateRequest(BaseModel):
    name: str
    metric: str
    condition: str
    threshold: float
    connection_id: str
    sql_query: str
    recipients: List[str]
    severity: str = "warning"
    description: str = ""


class AlertUpdateRequest(BaseModel):
    name: Optional[str] = None
    threshold: Optional[float] = None
    condition: Optional[str] = None
    recipients: Optional[List[str]] = None
    severity: Optional[str] = None
    description: Optional[str] = None


@router.post("/alerts")
async def create_alert(
    request: AlertCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        alert = alert_service.create_alert(
            name=request.name,
            metric=request.metric,
            condition=request.condition,
            threshold=request.threshold,
            connection_id=request.connection_id,
            sql_query=request.sql_query,
            recipients=request.recipients,
            severity=request.severity,
            description=request.description,
        )
        return {"success": True, "alert": alert}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/alerts")
async def list_alerts(current_user: dict = Depends(get_current_user)):
    return {"alerts": alert_service.list_alerts()}


@router.get("/alerts/history/all")
async def get_all_alert_history(
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    return {"history": alert_service.get_history(limit=limit)}


@router.get("/alerts/{alert_id}")
async def get_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    alert = alert_service.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.put("/alerts/{alert_id}")
async def update_alert(
    alert_id: str,
    request: AlertUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    updates = {k: v for k, v in request.dict().items() if v is not None}
    alert = alert_service.update_alert(alert_id, updates)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"success": True, "alert": alert}


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    success = alert_service.delete_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"success": True, "message": "Alert deleted"}


@router.post("/alerts/{alert_id}/pause")
async def pause_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    success = alert_service.pause_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"success": True, "message": "Alert paused"}


@router.post("/alerts/{alert_id}/resume")
async def resume_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    success = alert_service.resume_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"success": True, "message": "Alert resumed"}


@router.post("/alerts/{alert_id}/check")
async def check_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    result = await alert_service.check_alert(alert_id)
    return result


@router.get("/alerts/{alert_id}/history")
async def get_alert_history(
    alert_id: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    return {"history": alert_service.get_history(alert_id=alert_id, limit=limit)}


# ==================== Report Endpoints ====================

class ReportCreateRequest(BaseModel):
    name: str
    description: str = ""
    connection_id: str
    sql_query: str
    schedule: Optional[str] = None
    recipients: Optional[List[str]] = []
    format: str = "excel"


@router.post("/reports")
async def create_report_template(
    request: ReportCreateRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        template = report_generator.register_template(
            name=request.name,
            description=request.description,
            connection_id=request.connection_id,
            sql_query=request.sql_query,
            schedule=request.schedule,
            recipients=request.recipients,
            format=request.format,
        )
        return {"success": True, "template": template}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/reports")
async def list_report_templates(current_user: dict = Depends(get_current_user)):
    return {"templates": report_generator.list_templates()}


@router.get("/reports/{template_id}")
async def get_report_template(
    template_id: str,
    current_user: dict = Depends(get_current_user)
):
    template = report_generator.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.delete("/reports/{template_id}")
async def delete_report_template(
    template_id: str,
    current_user: dict = Depends(get_current_user)
):
    success = report_generator.delete_template(template_id)
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"success": True, "message": "Template deleted"}


@router.post("/reports/{template_id}/run")
async def run_report(
    template_id: str,
    send_email: bool = False,
    current_user: dict = Depends(get_current_user)
):
    result = await report_generator.generate_report(
        template_id=template_id,
        send_email=send_email,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/reports/{template_id}/send")
async def send_report_now(
    template_id: str,
    current_user: dict = Depends(get_current_user)
):
    result = await report_generator.generate_report(
        template_id=template_id,
        send_email=True,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result