"""
Database connection manager for PostgreSQL and MySQL.
Provides async connection pooling and query execution.
"""

import ssl
import logging
from typing import Optional, List, Dict, Any, Tuple
from contextlib import asynccontextmanager

from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    AsyncEngine,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from ..models.database import (
    DatabaseConnection,
    TableInfo,
    ColumnInfo,
    ForeignKeyInfo,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Production-grade async database manager.
    """

    def __init__(self):
        self._engines: Dict[str, AsyncEngine] = {}
        self._sessions: Dict[str, sessionmaker] = {}
        self._connection_cache: Dict[str, DatabaseConnection] = {}

    # ---------------------------------------------------------
    # SSL HELPER
    # ---------------------------------------------------------

    def _build_connect_args(self, connection: DatabaseConnection) -> dict:
        """Build connect_args with SSL if required."""
        connect_args = {}
        if connection.ssl_mode and connection.ssl_mode.lower() == "require":
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            connect_args["ssl"] = ssl_ctx
        return connect_args

    # ---------------------------------------------------------
    # ENGINE CREATION
    # ---------------------------------------------------------

    async def _create_engine(self, connection: DatabaseConnection) -> AsyncEngine:
        """Create async engine with connection pooling."""

        cache_key = connection.id or connection.connection_string

        if cache_key in self._engines:
            return self._engines[cache_key]

        dialect = connection.dialect.value

        if dialect == "postgresql":
            async_dialect = "postgresql+asyncpg"
        elif dialect in ["mysql", "mariadb"]:
            async_dialect = "mysql+aiomysql"
        else:
            raise ValueError(f"Unsupported dialect: {dialect}")

        password = connection.password or ""

        async_url = (
            f"{async_dialect}://{connection.username}:{password}"
            f"@{connection.host}:{connection.port}/{connection.database}"
        )

        connect_args = self._build_connect_args(connection)

        engine = create_async_engine(
            async_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
            connect_args=connect_args,
        )

        self._engines[cache_key] = engine
        self._connection_cache[cache_key] = connection

        return engine

    # ---------------------------------------------------------
    # CONNECTION MANAGEMENT
    # ---------------------------------------------------------

    async def connect(self, connection: DatabaseConnection) -> bool:
        try:
            engine = await self._create_engine(connection)

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            cache_key = connection.id or connection.connection_string

            async_session = sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            self._sessions[cache_key] = async_session

            logger.info(f"Connected to database: {connection.name}")
            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def disconnect(self, connection_id: str) -> bool:
        if connection_id in self._engines:
            await self._engines[connection_id].dispose()
            del self._engines[connection_id]

        self._sessions.pop(connection_id, None)
        self._connection_cache.pop(connection_id, None)

        return True

    async def test_connection(self, connection: DatabaseConnection) -> Tuple[bool, str]:
        """Test if a database connection is valid."""
        try:
            dialect = connection.dialect.value

            if dialect == "postgresql":
                async_dialect = "postgresql+asyncpg"
            elif dialect in ["mysql", "mariadb"]:
                async_dialect = "mysql+aiomysql"
            else:
                raise ValueError(f"Unsupported dialect: {dialect}")

            password = connection.password or ""

            async_url = (
                f"{async_dialect}://{connection.username}:{password}"
                f"@{connection.host}:{connection.port}/{connection.database}"
            )

            connect_args = self._build_connect_args(connection)

            engine = create_async_engine(
                async_url,
                pool_size=1,
                max_overflow=0,
                echo=False,
                connect_args=connect_args,
            )

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            await engine.dispose()

            return True, "Connection successful"

        except Exception as e:
            logger.error(f"Test connection failed: {e}")
            return False, str(e)

    # ---------------------------------------------------------
    # SESSION HANDLER
    # ---------------------------------------------------------

    @asynccontextmanager
    async def get_session(self, connection_id: str):
        if connection_id not in self._sessions:
            raise ValueError(f"No active session for: {connection_id}")

        async_session = self._sessions[connection_id]

        async with async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # ---------------------------------------------------------
    # QUERY EXECUTION
    # ---------------------------------------------------------

    async def execute_query(
        self,
        connection_id: str,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, List[str], List[Dict[str, Any]], str]:

        try:
            async with self.get_session(connection_id) as session:
                result = await session.execute(text(sql), params or {})

                columns = list(result.keys())
                rows = result.fetchall()

                data = [dict(zip(columns, row)) for row in rows]

                return True, columns, data, ""

        except SQLAlchemyError as e:
            logger.error(f"Query failed: {e}")
            return False, [], [], str(e)

    # ---------------------------------------------------------
    # TABLE INFO
    # ---------------------------------------------------------

    async def list_tables(self, connection_id: str) -> List[str]:
        try:
            engine = self._engines.get(connection_id)
            if not engine:
                return []

            async with engine.begin() as conn:
                return await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_table_names()
                )

        except Exception as e:
            logger.error(f"Failed to list tables: {e}")
            return []

    async def get_table_info(
        self,
        connection_id: str,
        table_name: str,
    ) -> Optional[TableInfo]:

        try:
            engine = self._engines.get(connection_id)
            if not engine:
                return None

            async with engine.begin() as conn:

                def get_metadata(sync_conn):
                    inspector = inspect(sync_conn)
                    columns_data = inspector.get_columns(table_name)
                    pk_data = inspector.get_pk_constraint(table_name)
                    fk_data = inspector.get_foreign_keys(table_name)
                    return columns_data, pk_data, fk_data

                columns_raw, pk_raw, fk_raw = await conn.run_sync(get_metadata)

                columns = [
                    ColumnInfo(
                        name=col["name"],
                        data_type=str(col["type"]),
                        is_nullable=col["nullable"],
                        is_primary_key=False,
                        default_value=str(col.get("default")) if col.get("default") else None,
                        comment=col.get("comment"),
                        ordinal_position=0,
                    )
                    for col in columns_raw
                ]

                primary_keys = pk_raw.get("constrained_columns", [])

                foreign_keys = [
                    ForeignKeyInfo(
                        name=fk.get("name", ""),
                        column=fk["constrained_columns"][0],
                        referenced_table=fk["referred_table"],
                        referenced_column=fk["referred_columns"][0],
                    )
                    for fk in fk_raw
                ]

                return TableInfo(
                    name=table_name,
                    columns=columns,
                    primary_keys=primary_keys,
                    foreign_keys=foreign_keys,
                    row_count=0,
                )

        except Exception as e:
            logger.error(f"Failed to get table info: {e}")
            return None


# Global instance
db_manager = DatabaseManager()
