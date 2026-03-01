"""
backend/api/dependencies.py

Central dependency injection layer for FastAPI.
Handles database sessions, service injection,
and request-level validations.
"""

from typing import Generator
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.models.database import SessionLocal
from backend.config import settings
from backend.services.database_manager import DatabaseManager
from backend.services.nl_to_sql import NLToSQLService
from backend.services.query_executor import QueryExecutor
from backend.utils.validators import validate_sql_query


# =====================================================
# DATABASE SESSION DEPENDENCY
# =====================================================

def get_db() -> Generator[Session, None, None]:
    """
    Provides a database session per request.
    Ensures proper cleanup.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# =====================================================
# CONFIG DEPENDENCY
# =====================================================

def get_settings():
    """
    Provides application settings.
    """
    return settings


# =====================================================
# SERVICE DEPENDENCIES
# =====================================================

def get_database_manager(
    db: Session = Depends(get_db)
) -> DatabaseManager:
    """
    Inject DatabaseManager service.
    """
    return DatabaseManager(db_session=db)


def get_nl_to_sql_service() -> NLToSQLService:
    """
    Inject NL to SQL service.
    """
    return NLToSQLService()


def get_query_executor(
    db_manager: DatabaseManager = Depends(get_database_manager)
) -> QueryExecutor:
    """
    Inject QueryExecutor service.
    """
    return QueryExecutor(db_manager=db_manager)


# =====================================================
# QUERY SAFETY VALIDATION
# =====================================================

FORBIDDEN_SQL_KEYWORDS = {
    "DROP",
    "DELETE",
    "TRUNCATE",
    "ALTER",
    "UPDATE"
}


def validate_query_safety(query: str) -> str:
    """
    Prevent destructive SQL queries from being executed.
    """
    upper_query = query.upper()

    for keyword in FORBIDDEN_SQL_KEYWORDS:
        if keyword in upper_query:
            raise HTTPException(
                status_code=400,
                detail=f"Unsafe SQL detected: '{keyword}' is not allowed."
            )

    return query


# =====================================================
# OPTIONAL: REQUEST CONTEXT DEPENDENCY
# =====================================================

def get_request_id(request: Request) -> str:
    """
    Extract request ID if present (future logging/tracing).
    """
    return request.headers.get("X-Request-ID", "unknown")