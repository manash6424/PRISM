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
        # Store resolved IPs separately
        self._resolved_hosts: Dict[str, str] = {}

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
                    import asyncpg
                    conn = DatabaseConnection(**conn_data)
                    conn.id = conn_id

                    # Always resolve hostname to IP
                    original_host = conn_data.get("host", conn.host)
                    resolved_host = self._resolve_host(original_host)

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

                    # Store resolved IP
                    self._resolved_hosts[conn_id] = resolved_host
                    self._connection_cache[conn_id] = conn
                    conn.status = ConnectionStatus.CONNECTED

                    logger.info(f"Restored connection: {conn.name} [{conn_id}] -> {resolved_host}")

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
    # ASYNCPG CONNECTION HELPER
    # ---------------------------------------------------------

    async def _get_asyncpg_conn(self, connection_id: str):
        """Get a direct asyncpg connection using resolved IP."""
        import asyncpg
        conn = self._connection_cache.get(connection_id)
        if not conn:
            raise ValueError(f"No connection found for: {connection_id}")

        resolved_host = self._resolved_hosts.get(connection_id)
        if not resolved_host:
            resolved_host = self._resolve_host(conn.host)
            self._resolved_hosts[connection_id] = resolved_host

        ssl_ctx = self._build_ssl_context()

        return await asyncpg.connect(
            host=resolved_host,
            port=conn.port,
            user=conn.username,
            password=conn.password or "",
            database=conn.database,
            ssl=ssl_ctx,
        )

    # ---------------------------------------------------------
    # ENGINE CREATION (kept for compatibility)
    # ---------------------------------------------------------

    def _get_cache_key(self, connection: DatabaseConnection) -> str:
        if connection.id:
            return connection.id
        return f"{connection.username}@{connection.host}:{connection.port}/{connection.database}"

    # ---------------------------------------------------------
    # CONNECTION MANAGEMENT
    # ---------------------------------------------------------

    async def connect(self, connection: DatabaseConnection) -> bool:
        try:
            import asyncpg
            cache_key = self._get_cache_key(connection)
            resolved_host = self._resolve_host(connection.host)
            ssl_ctx = self._build_ssl_context()

            # Test connection with asyncpg
            pg_conn = await asyncpg.connect(
                host=resolved_host,
                port=connection.port,
                user=connection.username,
                password=connection.password or "",
                database=connection.database,
                ssl=ssl_ctx,
            )
            await pg_conn.execute("SELECT 1")
            await pg_conn.close()

            # Store resolved IP and connection
            self._resolved_hosts[cache_key] = resolved_host
            connection.status = ConnectionStatus.CONNECTED
            self._connection_cache[cache_key] = connection

            # Also store in _sessions as a marker that connection is active
            self._sessions[cache_key] = True

            logger.info(f"Connected to database: {connection.name} -> {resolved_host}")
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
        self._resolved_hosts.pop(connection_id, None)
        self._delete_persisted_connection(connection_id)

        return True

    async def disconnect_all(self) -> None:
        for conn_id in list(self._engines.keys()):
            await self._engines[conn_id].dispose()
        self._engines.clear()
        self._sessions.clear()
        self._connection_cache.clear()
        self._resolved_hosts.clear()
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
                password = connection.password or ""
                async_url = (
                    f"mysql+aiomysql://{connection.username}:{password}"
                    f"@{resolved_host}:{connection.port}/{connection.database}"
                )
                engine = create_async_engine(async_url, pool_size=1, max_overflow=0, echo=False)
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
    # SESSION HANDLER (kept for compatibility)
    # ---------------------------------------------------------

    @asynccontextmanager
    async def get_session(self, connection_id: str):
        """Compatibility wrapper - yields a mock session for asyncpg usage."""
        conn = self._connection_cache.get(connection_id)
        if not conn:
            raise ValueError(f"No connection found for: {connection_id}")
        yield connection_id

    # ---------------------------------------------------------
    # QUERY EXECUTION - Uses asyncpg directly
    # ---------------------------------------------------------

    async def execute_query(
        self,
        connection_id: str,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, List[str], List[Dict[str, Any]], str]:

        pg_conn = None
        try:
            pg_conn = await self._get_asyncpg_conn(connection_id)
            
            if params:
                rows = await pg_conn.fetch(sql, *params.values())
            else:
                rows = await pg_conn.fetch(sql)

            if rows:
                columns = list(rows[0].keys())
                data = [dict(row) for row in rows]
            else:
                # Get column names from empty result
                stmt = await pg_conn.prepare(sql)
                columns = [attr.name for attr in stmt.get_attributes()]
                data = []

            return True, columns, data, ""

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return False, [], [], str(e)
        finally:
            if pg_conn:
                await pg_conn.close()

    # ---------------------------------------------------------
    # TABLE INFO - Uses asyncpg directly
    # ---------------------------------------------------------

    async def list_tables(self, connection_id: str) -> List[str]:
        pg_conn = None
        try:
            pg_conn = await self._get_asyncpg_conn(connection_id)
            rows = await pg_conn.fetch("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            return [row['table_name'] for row in rows]

        except Exception as e:
            logger.error(f"Failed to list tables: {e}")
            return []
        finally:
            if pg_conn:
                await pg_conn.close()

    async def get_table_info(
        self,
        connection_id: str,
        table_name: str,
    ) -> Optional[TableInfo]:

        pg_conn = None
        try:
            pg_conn = await self._get_asyncpg_conn(connection_id)

            # Get columns
            columns_rows = await pg_conn.fetch("""
                SELECT 
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    ordinal_position
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
            """, table_name)

            # Get primary keys
            pk_rows = await pg_conn.fetch("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_name = $1
                AND tc.table_schema = 'public'
            """, table_name)
            primary_keys = [row['column_name'] for row in pk_rows]

            # Get foreign keys
            fk_rows = await pg_conn.fetch("""
                SELECT
                    kcu.column_name,
                    ccu.table_name AS referenced_table,
                    ccu.column_name AS referenced_column,
                    tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_name = $1
                AND tc.table_schema = 'public'
            """, table_name)

            columns = [
                ColumnInfo(
                    name=row['column_name'],
                    data_type=row['data_type'],
                    is_nullable=row['is_nullable'] == 'YES',
                    is_primary_key=row['column_name'] in primary_keys,
                    default_value=str(row['column_default']) if row['column_default'] else None,
                    comment=None,
                    ordinal_position=row['ordinal_position'],
                )
                for row in columns_rows
            ]

            foreign_keys = [
                ForeignKeyInfo(
                    name=row['constraint_name'] or "",
                    column=row['column_name'],
                    referenced_table=row['referenced_table'],
                    referenced_column=row['referenced_column'],
                )
                for row in fk_rows
            ]

            return TableInfo(
                name=table_name,
                columns=columns,
                primary_keys=primary_keys,
                foreign_keys=foreign_keys,
                row_count=0,
            )

        except Exception as e:
            logger.error(f"Failed to get table info for {table_name}: {e}")
            return None
        finally:
            if pg_conn:
                await pg_conn.close()


# Global instance
db_manager = DatabaseManager()