"""
Query executor service for natural language to SQL conversion and execution.
"""
import uuid
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from ..models.database import QueryRequest, QueryResponse, DatabaseDialect
from .database_manager import db_manager
from .nl_to_sql import nl_to_sql
from .schema_discovery import schema_discovery
from ..utils.sql_formatter import format_sql

logger = logging.getLogger(__name__)


class QueryExecutor:
    """
    Executes natural language queries against databases.
    Handles NL to SQL conversion, execution, and response formatting.
    """

    def __init__(self):
        self._query_history: Dict[str, QueryResponse] = {}

    async def execute(self, request: QueryRequest) -> QueryResponse:
        query_id = str(uuid.uuid4())
        start_time = time.time()

        try:
            schema_data = await schema_discovery.discover_full_schema(request.connection_id)
            dialect = request.dialect or DatabaseDialect.POSTGRESQL
            schema_context = schema_discovery.generate_schema_context(schema_data, dialect)

            generated_sql, explanation = await nl_to_sql.convert(
                natural_language=request.natural_language,
                schema_context=schema_context,
                dialect=dialect,
                include_explanation=request.include_explanation,
            )

            formatted_sql = format_sql(generated_sql, dialect.value)

            success, columns, results, error = await db_manager.execute_query(
                connection_id=request.connection_id,
                sql=formatted_sql,
            )

            execution_time = (time.time() - start_time) * 1000

            response = QueryResponse(
                query_id=query_id,
                natural_language=request.natural_language,
                generated_sql=formatted_sql,
                explanation=explanation,
                success=success,
                error_message=error if not success else None,
                execution_time_ms=execution_time,
                row_count=len(results) if success else 0,
                columns=columns,
                results=results[:request.max_results] if success else [],
                timestamp=datetime.utcnow(),
            )

            self._query_history[query_id] = response
            logger.info(f"Query executed: {query_id} - {response.row_count} rows in {execution_time:.2f}ms")
            return response

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Query execution failed: {e}")

            error_response = QueryResponse(
                query_id=query_id,
                natural_language=request.natural_language,
                generated_sql="",
                explanation=None,
                success=False,
                error_message=str(e),
                execution_time_ms=execution_time,
                row_count=0,
                columns=[],
                results=[],
                timestamp=datetime.utcnow(),
            )

            self._query_history[query_id] = error_response
            return error_response

    async def execute_raw_sql(self, connection_id: str, sql: str) -> QueryResponse:
        query_id = str(uuid.uuid4())
        start_time = time.time()

        try:
            success, columns, results, error = await db_manager.execute_query(
                connection_id=connection_id,
                sql=sql,
            )

            execution_time = (time.time() - start_time) * 1000

            response = QueryResponse(
                query_id=query_id,
                natural_language=f"Raw SQL: {sql[:100]}...",
                generated_sql=sql,
                explanation="Direct SQL execution",
                success=success,
                error_message=error if not success else None,
                execution_time_ms=execution_time,
                row_count=len(results) if success else 0,
                columns=columns,
                results=results,
                timestamp=datetime.utcnow(),
            )

            self._query_history[query_id] = response
            return response

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Raw SQL execution failed: {e}")

            error_response = QueryResponse(
                query_id=query_id,
                natural_language=f"Raw SQL: {sql[:100]}...",
                generated_sql=sql,
                explanation=None,
                success=False,
                error_message=str(e),
                execution_time_ms=execution_time,
                row_count=0,
                columns=[],
                results=[],
                timestamp=datetime.utcnow(),
            )

            self._query_history[query_id] = error_response
            return error_response

    def get_query_history(self, connection_id: Optional[str] = None, limit: int = 50) -> list[QueryResponse]:
        history = list(self._query_history.values())
        if connection_id is not None:
            history = [q for q in history if q.connection_id == connection_id]
        history.sort(key=lambda x: x.timestamp, reverse=True)
        return history[:limit]

    def get_query_by_id(self, query_id: str) -> Optional[QueryResponse]:
        return self._query_history.get(query_id)


# Global query executor
query_executor = QueryExecutor()