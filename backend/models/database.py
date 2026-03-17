"""
Database models for AI Desktop Copilot.
Defines schemas for connections, queries, and results.
"""

from datetime import datetime, timezone
from typing import Optional, List, Any, Dict
from enum import Enum

from pydantic import BaseModel, Field


# ==================== Enums ====================

class DatabaseDialect(str, Enum):
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    MARIADB = "mariadb"


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    PENDING = "pending"


class ExportFormat(str, Enum):
    CSV = "csv"
    EXCEL = "xlsx"
    PDF = "pdf"
    JSON = "json"


# ==================== Schema Models ====================

class ColumnInfo(BaseModel):
    name: str = Field(..., description="Column name")
    data_type: str = Field(..., description="SQL data type")
    is_nullable: bool = Field(default=True)
    is_primary_key: bool = Field(default=False)
    default_value: Optional[str] = Field(None)
    comment: Optional[str] = Field(None)
    ordinal_position: int = Field(default=0)


class ForeignKeyInfo(BaseModel):
    name: str = Field(..., description="Foreign key constraint name")
    column: str = Field(..., description="Local column name")
    referenced_table: str = Field(..., description="Referenced table name")
    referenced_column: str = Field(..., description="Referenced column name")


class TableInfo(BaseModel):
    name: str = Field(..., description="Table name")
    db_schema: Optional[str] = Field(None, description="Database schema")  # renamed from schema
    columns: List[ColumnInfo] = Field(default_factory=list)
    primary_keys: List[str] = Field(default_factory=list)
    foreign_keys: List[ForeignKeyInfo] = Field(default_factory=list)
    row_count: Optional[int] = Field(None)
    comment: Optional[str] = Field(None)


# ==================== Connection Model ====================

class DatabaseConnection(BaseModel):
    id: Optional[str] = Field(None)
    name: str = Field(..., min_length=1, max_length=100)
    dialect: DatabaseDialect = Field(...)
    host: str = Field(...)
    port: int = Field(..., ge=1, le=65535)
    database: str = Field(..., min_length=1)
    username: str = Field(...)
    password: Optional[str] = Field(None)
    db_schema: str = Field(default="public", description="Default schema")  # renamed from schema
    ssl_mode: Optional[str] = Field(None)
    status: ConnectionStatus = Field(default=ConnectionStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_connected_at: Optional[datetime] = Field(None)

    @property
    def connection_string(self) -> str:
        password_part = f":{self.password}" if self.password else ""
        ssl_part = f"?sslmode={self.ssl_mode}" if self.ssl_mode else ""
        return (
            f"{self.dialect.value}://{self.username}"
            f"{password_part}@{self.host}:{self.port}/{self.database}{ssl_part}"
        )

    @property
    def safe_connection_string(self) -> str:
        return (
            f"{self.dialect.value}://{self.username}:****"
            f"@{self.host}:{self.port}/{self.database}"
        )

    def touch(self):
        self.updated_at = datetime.now(timezone.utc)


# ==================== Query Models ====================

class QueryRequest(BaseModel):
    connection_id: str = Field(...)
    natural_language: str = Field(..., min_length=1, max_length=5000)
    dialect: Optional[DatabaseDialect] = Field(None)
    include_explanation: bool = Field(default=True)
    max_results: int = Field(default=1000, ge=1, le=100000)


class QueryResponse(BaseModel):
    query_id: str = Field(...)
    natural_language: str = Field(...)
    generated_sql: str = Field(...)
    explanation: Optional[str] = Field(None)
    success: bool = Field(...)
    error_message: Optional[str] = Field(None)
    execution_time_ms: float = Field(default=0.0)
    row_count: int = Field(default=0)
    columns: List[str] = Field(default_factory=list)
    results: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==================== Export Models ====================

class ExportRequest(BaseModel):
    query_id: str = Field(...)
    format: ExportFormat = Field(...)
    filename: Optional[str] = Field(None)
    include_headers: bool = Field(default=True)
    title: Optional[str] = Field(None)
    description: Optional[str] = Field(None)
    chart_image: Optional[str] = Field(None)


# ==================== Alert Model ====================

class AlertRule(BaseModel):
    id: Optional[str] = Field(None)
    name: str = Field(..., min_length=1, max_length=100)
    connection_id: str = Field(...)
    query_template: str = Field(...)
    condition: str = Field(...)
    frequency_minutes: int = Field(default=60, ge=1)
    channels: List[str] = Field(default_factory=list)
    is_active: bool = Field(default=True)
    last_triggered: Optional[datetime] = Field(None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))