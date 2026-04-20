import ssl
import json
import socket
import logging
import os
import hashlib
from typing import Optional, List, Dict, Any, Tuple
from contextlib import asynccontextmanager

from sqlalchemy import text
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

CONNECTIONS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "../../connections"
)

os.makedirs(CONNECTIONS_DIR, exist_ok=True)

# ✅ Supabase pooler hosts — never resolve to IP, use hostname directly
POOLER_HOSTS = [
    "pooler.supabase.com",
    "supabase.co",
    "supabase.in",
]

def is_pooler_host(host: str) -> bool:
    return any(h in host for h in POOLER_HOSTS)


class DatabaseManager:
    """Production-grade async database manager with per-user persistence."""

    def __init__(self):
        self._engines: Dict[str, AsyncEngine] = {}
        self._sessions: Dict[str, sessionmaker] = {}
        self._connection_cache: Dict[str, DatabaseConnection] = {}
        self._resolved_hosts: Dict[str, str] = {}
        self._connection_users: Dict[str, str] = {}

    # ---------------------------------------------------------
    # PERSISTENCE — Per User
    # ---------------------------------------------------------

    def _get_connections_file(self, user_id: str) -> str:
        safe_id = hashlib.md5(user_id.encode()).hexdigest()
        return os.path.join(CONNECTIONS_DIR, f"connections_{safe_id}.json")

    def _save_connections(self, user_id: str) -> None:
        try:
            filepath = self._get_connections_file(user_id)
            data = {}
            for conn_id, conn in self._connection_cache.items():
                if self._connection_users.get(conn_id) == user_id:
                    data[conn_id] = conn.model_dump(mode="json")
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.info(f"Saved {len(data)} connection(s) for user {user_id[:8]}...")
        except Exception as e:
            logger.error(f"Failed to save connections: {e}")

    async def load_connections_for_user(self, user_id: str) -> None:
        filepath = self._get_connections_file(user_id)
        if not os.path.exists(filepath):
            logger.info(f"No persisted connections for user {user_id[:8]}...")
            return

        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            for conn_id, conn_data in data.items():
                if conn_id in self._connection_cache:
                    continue
                try:
                    conn = DatabaseConnection(**conn_data)
                    conn.id = conn_id
                    original_host = conn_data.get("host", conn.host)
                    resolved_host = self._resolve_host(original_host)
                    pg_conn = await self._make_asyncpg_connection(
                        resolved_host, conn.port, conn.username,
                        conn.password or "", conn.database
                    )
                    await pg_conn.execute("SELECT 1")
                    await pg_conn.close()

                    self._resolved_hosts[conn_id] = resolved_host
                    self._connection_cache[conn_id] = conn
                    self._connection_users[conn_id] = user_id
                    self._sessions[conn_id] = True
                    conn.status = ConnectionStatus.CONNECTED
                    logger.info(f"Restored connection: {conn.name}")
                except Exception as e:
                    logger.error(f"Failed to restore connection {conn_id}: {e}")

        except Exception as e:
            logger.error(f"Failed to load connections for user {user_id[:8]}...: {e}")

    async def load_connections(self) -> None:
        if not os.path.exists(CONNECTIONS_DIR):
            return
        try:
            for filename in os.listdir(CONNECTIONS_DIR):
                if filename.startswith("connections_") and filename.endswith(".json"):
                    filepath = os.path.join(CONNECTIONS_DIR, filename)
                    try:
                        with open(filepath, "r") as f:
                            data = json.load(f)
                        for conn_id, conn_data in data.items():
                            if conn_id in self._connection_cache:
                                continue
                            try:
                                conn = DatabaseConnection(**conn_data)
                                conn.id = conn_id
                                original_host = conn_data.get("host", conn.host)
                                resolved_host = self._resolve_host(original_host)
                                pg_conn = await self._make_asyncpg_connection(
                                    resolved_host, conn.port, conn.username,
                                    conn.password or "", conn.database
                                )
                                await pg_conn.execute("SELECT 1")
                                await pg_conn.close()
                                self._resolved_hosts[conn_id] = resolved_host
                                self._connection_cache[conn_id] = conn
                                self._sessions[conn_id] = True
                                conn.status = ConnectionStatus.CONNECTED
                                user_hash = filename.replace("connections_", "").replace(".json", "")
                                self._connection_users[conn_id] = conn_data.get("user_id", user_hash)
                                logger.info(f"Restored connection: {conn.name}")
                            except Exception as e:
                                logger.error(f"Failed to restore connection {conn_id}: {e}")
                    except Exception as e:
                        logger.error(f"Failed to load {filename}: {e}")
        except Exception as e:
            logger.error(f"Failed to load connections: {e}")

    def _delete_persisted_connection(self, connection_id: str) -> None:
        user_id = self._connection_users.get(connection_id)
        if not user_id:
            return
        filepath = self._get_connections_file(user_id)
        if not os.path.exists(filepath):
            return
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            data.pop(connection_id, None)
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to delete persisted connection: {e}")

    # ---------------------------------------------------------
    # USER ISOLATION
    # ---------------------------------------------------------

    def get_user_connections(self, user_id: str) -> Dict[str, DatabaseConnection]:
        return {
            conn_id: conn
            for conn_id, conn in self._connection_cache.items()
            if self._connection_users.get(conn_id) == user_id
        }

    def is_connection_owned_by_user(self, connection_id: str, user_id: str) -> bool:
        return self._connection_users.get(connection_id) == user_id

    # ---------------------------------------------------------
    # DNS RESOLVER
    # ---------------------------------------------------------

    def _resolve_host(self, host: str) -> str:
        """Resolve hostname to IP, but keep pooler/supabase hosts as-is."""
        # ✅ Never resolve Supabase hosts — pass hostname directly to asyncpg
        if is_pooler_host(host):
            logger.info(f"Supabase host detected, using hostname directly: {host}")
            return host
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

    # ---------------------------------------------------------
    # ✅ CENTRAL ASYNCPG CONNECTION BUILDER
    # ---------------------------------------------------------

    async def _make_asyncpg_connection(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
    ):
        """Build asyncpg connection — handles both direct and pooler connections."""
        import asyncpg
        ssl_ctx = self._build_ssl_context()

        return await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            ssl=ssl_ctx,
            timeout=30,
            command_timeout=60,
        )

    # ---------------------------------------------------------
    # ASYNCPG CONNECTION HELPER
    # ---------------------------------------------------------

    async def _get_asyncpg_conn(self, connection_id: str):
        conn = self._connection_cache.get(connection_id)
        if not conn:
            raise ValueError(f"No connection found for: {connection_id}")

        resolved_host = self._resolved_hosts.get(connection_id)
        if not resolved_host:
            resolved_host = self._resolve_host(conn.host)
            self._resolved_hosts[connection_id] = resolved_host

        return await self._make_asyncpg_connection(
            resolved_host, conn.port, conn.username,
            conn.password or "", conn.database
        )

    # ---------------------------------------------------------
    # ENGINE CREATION
    # ---------------------------------------------------------

    def _get_cache_key(self, connection: DatabaseConnection) -> str:
        if connection.id:
            return connection.id
        return f"{connection.username}@{connection.host}:{connection.port}/{connection.database}"

    # ---------------------------------------------------------
    # CONNECTION MANAGEMENT
    # ---------------------------------------------------------

    async def connect(self, connection: DatabaseConnection, user_id: str = None) -> bool:
        try:
            cache_key = self._get_cache_key(connection)
            resolved_host = self._resolve_host(connection.host)

            pg_conn = await self._make_asyncpg_connection(
                resolved_host, connection.port, connection.username,
                connection.password or "", connection.database
            )
            await pg_conn.execute("SELECT 1")
            await pg_conn.close()

            self._resolved_hosts[cache_key] = resolved_host
            connection.status = ConnectionStatus.CONNECTED
            self._connection_cache[cache_key] = connection
            self._sessions[cache_key] = True

            if user_id:
                self._connection_users[cache_key] = user_id

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
        self._connection_users.pop(connection_id, None)
        return True

    async def disconnect_all(self) -> None:
        for conn_id in list(self._engines.keys()):
            await self._engines[conn_id].dispose()
        self._engines.clear()
        self._sessions.clear()
        self._connection_cache.clear()
        self._resolved_hosts.clear()
        self._connection_users.clear()
        logger.info("All database connections closed.")

    async def test_connection(self, connection: DatabaseConnection) -> Tuple[bool, str]:
        try:
            dialect = connection.dialect.value
            resolved_host = self._resolve_host(connection.host)

            if dialect == "postgresql":
                pg_conn = await self._make_asyncpg_connection(
                    resolved_host, connection.port, connection.username,
                    connection.password or "", connection.database
                )
                await pg_conn.execute("SELECT 1")
                await pg_conn.close()
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
    # SESSION HANDLER
    # ---------------------------------------------------------

    @asynccontextmanager
    async def get_session(self, connection_id: str):
        conn = self._connection_cache.get(connection_id)
        if not conn:
            raise ValueError(f"No connection found for: {connection_id}")
        yield connection_id

    # ---------------------------------------------------------
    # QUERY EXECUTION
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
    # TABLE INFO
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

            columns_rows = await pg_conn.fetch("""
                SELECT column_name, data_type, is_nullable, column_default, ordinal_position
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
            """, table_name)

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

            fk_rows = await pg_conn.fetch("""
                SELECT kcu.column_name, ccu.table_name AS referenced_table,
                       ccu.column_name AS referenced_column, tc.constraint_name
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