"""
Query-related models for AI Desktop Copilot.
Handles query execution, history, and metadata.
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


# ==================== Enums ====================

class QueryType(str, Enum):
    """Type of query executed."""
    NATURAL_LANGUAGE = "natural_language"
    RAW_SQL = "raw_sql"


class QueryStatus(str, Enum):
    """Execution status of a query."""
    SUCCESS = "success"
    FAILED = "failed"
    RUNNING = "running"


# ==================== Request Models ====================

class RawSQLRequest(BaseModel):
    """Raw SQL execution request."""
    connection_id: str = Field(..., description="Database connection ID")
    sql: str = Field(..., min_length=1, description="SQL query string")
    max_results: int = Field(
        default=1000,
        ge=1,
        le=100000,
        description="Maximum number of rows to return"
    )


# ==================== Query Execution Models ====================

class QueryExecution(BaseModel):
    """Stores metadata about a query execution."""
    query_id: str = Field(..., description="Unique query ID")
    connection_id: str = Field(..., description="Database connection ID")
    query_type: QueryType = Field(..., description="Type of query")
    natural_language: Optional[str] = Field(
        None,
        description="Original natural language query"
    )
    sql: str = Field(..., description="Executed SQL query")

    status: QueryStatus = Field(
        default=QueryStatus.RUNNING,
        description="Current execution status"
    )

    execution_time_ms: float = Field(
        default=0.0,
        description="Execution time in milliseconds"
    )

    row_count: int = Field(
        default=0,
        description="Number of rows returned"
    )

    error_message: Optional[str] = Field(
        None,
        description="Error message if execution failed"
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    completed_at: Optional[datetime] = Field(
        None,
        description="Timestamp when execution completed"
    )

    def mark_completed(self, success: bool, error: Optional[str] = None):
        """Mark query execution as completed."""
        self.status = QueryStatus.SUCCESS if success else QueryStatus.FAILED
        self.error_message = error
        self.completed_at = datetime.now(timezone.utc)


# ==================== Pagination Model ====================

class QueryPagination(BaseModel):
    """Pagination configuration for large result sets."""
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=100, ge=1, le=10000, description="Rows per page")


# ==================== Statistics Model ====================

class QueryStatistics(BaseModel):
    """Aggregate query statistics."""
    total_queries: int = Field(default=0)
    successful_queries: int = Field(default=0)
    failed_queries: int = Field(default=0)
    average_execution_time_ms: float = Field(default=0.0)
    last_executed_at: Optional[datetime] = None