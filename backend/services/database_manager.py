"""
Database connection manager for PostgreSQL and MySQL.
Provides async connection pooling and query execution.
"""

import ssl
import json
import socket
import logging
import os
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
    ConnectionStatus,
)

logger = logging.getLogger(__name__)

CONNECTIONS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "../../connections.json"
)


class DatabaseManager:
    """Production-grade async database manager with persistence."""

    def __init__(self):
        self._engines: Dict[str, AsyncEngine] = {}
        self._sessions: Dict[str, sessionmaker] = {}
        self._connection_cache: Dict[str, DatabaseConnection] = {}

    # ---------------------------------------------------------
    # PERSISTENCE
    # ---------------------------------------------------------

    def _save_connections(self) -> None:
        try:
            data = {}
            for conn_id, conn in self._connection_cache.items():
                data[conn_id] = conn.model_dump(mode="json")
            with open(CONNECTIONS_FILE, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.info(f"Saved {len(data)} connection(s) to disk.")
        except Exception as e:
            logger.error(f"Failed to save connections: {e}")

    async def load_connections(self) -> None:
        """Load and reconnect all persisted connections on startup."""
        if not os.path.exists(CONNECTIONS_FILE):
            logger.info("No persisted connections found.")
            return

        try:
            with open(CONNECTIONS_FILE, "r") as f:
                data = json.load(f)

            logger.info(f"Loading {len(data)} persisted connection(s)...")

            for conn_id, conn_data in data.items():
                try:
                    conn = DatabaseConnection(**conn_data)
                    conn.id = conn_id

                    import asyncpg
                    resolved_host = self._resolve_host(conn.host)
                    ssl_ctx = self._build_ssl_context()

                    # Test with asyncpg directly using resolved IP
                    pg_conn = await asyncpg.connect(
                        host=resolved_host,
                        port=conn.port,
                        user=conn.username,
                        password=conn.password or "",
                        database=conn.database,
                        ssl=ssl_ctx,
                    )
                    await pg_conn.execute("SELECT 1")
                    await pg_conn.close()

                    # ✅ KEY FIX: Store resolved IP as host so all future queries use IP
                    conn.host = resolved_host

                    password = conn.password or ""
                    async_url = (
                        f"postgresql+asyncpg://{conn.username}:{password}"
                        f"@{resolved_host}:{conn.port}/{conn.database}"
                    )

                    engine = create_async_engine(
                        async_url,
                        pool_size=5,
                        max_overflow=10,
                        pool_pre_ping=True,
                        pool_recycle=3600,
                        echo=False,
                        connect_args={"ssl": ssl_ctx},
                    )

                    self._engines[conn_id] = engine
                    self._connection_cache[conn_id] = conn

                    async_session = sessionmaker(
                        engine,
                        class_=AsyncSession,
                        expire_on_commit=False,
                    )
                    self._sessions[conn_id] = async_session
                    conn.status = ConnectionStatus.CONNECTED

                    logger.info(f"Restored connection: {conn.name} [{conn_id}]")

                except Exception as e:
                    logger.error(f"Failed to restore connection {conn_id}: {e}")

        except Exception as e:
            logger.error(f"Failed to load connections file: {e}")

    def _delete_persisted_connection(self, connection_id: str) -> None:
        if not os.path.exists(CONNECTIONS_FILE):
            return
        try:
            with open(CONNECTIONS_FILE, "r") as f:
                data = json.load(f)
            data.pop(connection_id, None)
            with open(CONNECTIONS_FILE, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to delete persisted connection: {e}")

    # ---------------------------------------------------------
    # DNS RESOLVER
    # ---------------------------------------------------------

    def _resolve_host(self, host: str) -> str:
        try:
            ip = socket.gethostbyname(host)
            logger.info(f"Resolved {host} -> {ip}")
            return ip
        except socket.gaierror:
            logger.warning(f"Could not resolve {host}, using as-is")
            return host

    # ---------------------------------------------------------
    # SSL HELPERS
    # ---------------------------------------------------------

    def _build_ssl_context(self) -> ssl.SSLContext:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        return ssl_ctx

    def _build_connect_args(self, connection: DatabaseConnection) -> dict:
        connect_args = {}
        if connection.ssl_mode and connection.ssl_mode.lower() == "require":
            connect_args["ssl"] = self._build_ssl_context()
        return connect_args

    # ---------------------------------------------------------
    # ENGINE CREATION
    # ---------------------------------------------------------

    def _build_async_url(self, connection: DatabaseConnection, resolved_host: str) -> str:
        dialect = connection.dialect.value
        if dialect == "postgresql":
            async_dialect = "postgresql+asyncpg"
        elif dialect in ["mysql", "mariadb"]:
            async_dialect = "mysql+aiomysql"
        else:
            raise ValueError(f"Unsupported dialect: {dialect}")

        password = connection.password or ""
        return (
            f"{async_dialect}://{connection.username}:{password}"
            f"@{resolved_host}:{connection.port}/{connection.database}"
        )

    def _get_cache_key(self, connection: DatabaseConnection) -> str:
        if connection.id:
            return connection.id
        return f"{connection.username}@{connection.host}:{connection.port}/{connection.database}"

    async def _create_engine(self, connection: DatabaseConnection) -> AsyncEngine:
        cache_key = self._get_cache_key(connection)

        if cache_key in self._engines:
            return self._engines[cache_key]

        # Always resolve hostname to IP to fix Windows DNS issue
        resolved_host = self._resolve_host(connection.host)

        # ✅ Store resolved IP so reconnects also use IP
        connection.host = resolved_host

        ssl_ctx = self._build_ssl_context()
        async_url = self._build_async_url(connection, resolved_host)

        engine = create_async_engine(
            async_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
            connect_args={"ssl": ssl_ctx},
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

            cache_key = self._get_cache_key(connection)

            async_session = sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            self._sessions[cache_key] = async_session
            connection.status = ConnectionStatus.CONNECTED
            self._connection_cache[cache_key] = connection

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
        self._delete_persisted_connection(connection_id)

        return True

    async def disconnect_all(self) -> None:
        for conn_id in list(self._engines.keys()):
            await self._engines[conn_id].dispose()
        self._engines.clear()
        self._sessions.clear()
        self._connection_cache.clear()
        logger.info("All database connections closed.")

    async def test_connection(self, connection: DatabaseConnection) -> Tuple[bool, str]:
        try:
            dialect = connection.dialect.value
            resolved_host = self._resolve_host(connection.host)

            if dialect == "postgresql":
                import asyncpg
                ssl_ctx = self._build_ssl_context()
                conn = await asyncpg.connect(
                    host=resolved_host,
                    port=connection.port,
                    user=connection.username,
                    password=connection.password or "",
                    database=connection.database,
                    ssl=ssl_ctx,
                )
                await conn.execute("SELECT 1")
                await conn.close()
                return True, "Connection successful"

            elif dialect in ["mysql", "mariadb"]:
                async_url = self._build_async_url(connection, resolved_host)
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

            else:
                return False, f"Unsupported dialect: {dialect}"

        except Exception as e:
            logger.error(f"Test connection failed: {e}")
            return False, str(e)

    # ---------------------------------------------------------
    # SESSION HANDLER
    # ---------------------------------------------------------

    @asynccontextmanager
    async def get_session(self, connection_id: str):
        if connection_id not in self._sessions:
            conn = self._connection_cache.get(connection_id)
            if conn:
                logger.warning(f"Session missing for {connection_id}, attempting reconnect...")
                success = await self.connect(conn)
                if not success:
                    raise ValueError(f"Could not reconnect to database: {connection_id}")
            else:
                raise ValueError(f"No connection found for: {connection_id}")

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

                primary_keys = pk_raw.get("constrained_columns", [])

                columns = [
                    ColumnInfo(
                        name=col["name"],
                        data_type=str(col["type"]),
                        is_nullable=col["nullable"],
                        is_primary_key=col["name"] in primary_keys,
                        default_value=str(col.get("default")) if col.get("default") else None,
                        comment=col.get("comment"),
                        ordinal_position=i,
                    )
                    for i, col in enumerate(columns_raw)
                ]

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