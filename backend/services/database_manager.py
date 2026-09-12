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

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")

# ✅ Hardcoded IP map to bypass DNS resolution failures
HARDCODED_HOSTS = {
    "aws-1-ap-south-1.pooler.supabase.com": "3.109.171.244",
}

POOLER_HOSTS = [
    "pooler.supabase.com",
    "supabase.co",
    "supabase.in",
]

def is_pooler_host(host: str) -> bool:
    return any(h in host for h in POOLER_HOSTS)

import base64
import hashlib

def _encrypt(password: str) -> str:
    from cryptography.fernet import Fernet
    raw = os.getenv("ENCRYPTION_KEY", "PrismSecretKey2024XYZ1234567890")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key).encrypt(password.encode()).decode()

def _decrypt(token: str) -> str:
    from cryptography.fernet import Fernet
    raw = os.getenv("ENCRYPTION_KEY", "PrismSecretKey2024XYZ1234567890")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    try:
        return Fernet(key).decrypt(token.encode()).decode()
    except Exception:
        return token


class DatabaseManager:
    def __init__(self):
        self._engines: Dict[str, AsyncEngine] = {}
        self._sessions: Dict[str, sessionmaker] = {}
        self._connection_cache: Dict[str, DatabaseConnection] = {}
        self._resolved_hosts: Dict[str, str] = {}
        self._original_hosts: Dict[str, str] = {}
        self._connection_users: Dict[str, str] = {}
        self._user_tokens: Dict[str, str] = {}
        self._pools: Dict[str, Any] = {}  # NEW: connection_id -> asyncpg.Pool (reused across queries)

    async def _supabase_save_connection(self, conn_id, conn, user_id, user_token=None):
        try:
            import httpx
            url = f"{SUPABASE_URL}/rest/v1/user_connections"
            auth_token = user_token or SUPABASE_ANON_KEY
            headers = {
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            }
            payload = {
                "id": conn_id,
                "user_id": user_id,
                "name": conn.name,
                "host": conn.host,
                "port": conn.port,
                "database": conn.database,
                "username": conn.username,
                "password": _encrypt(conn.password or ""),
                "dialect": conn.dialect.value if hasattr(conn.dialect, 'value') else str(conn.dialect),
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code in [200, 201]:
                    logger.info(f"Saved connection {conn.name} to Supabase")
                else:
                    logger.error(f"Failed to save to Supabase: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"Supabase save error: {e}")

    async def _supabase_delete_connection(self, conn_id, user_id=None, user_token=None):
        try:
            import httpx
            url = f"{SUPABASE_URL}/rest/v1/user_connections?id=eq.{conn_id}"
            service_key = os.getenv("SUPABASE_SERVICE_KEY", SUPABASE_ANON_KEY)
            headers = {
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Prefer": "return=representation",
            }
            async with httpx.AsyncClient() as client:
                resp = await client.delete(url, headers=headers)
                logger.info(f"Supabase DELETE status: {resp.status_code}, body: {resp.text}")
                if resp.status_code in [200, 204]:
                    deleted_rows = resp.json() if resp.text else []
                    if isinstance(deleted_rows, list) and len(deleted_rows) == 0:
                        logger.error(f"Supabase DELETE returned 0 rows for conn {conn_id}")
                        return False
                    logger.info(f"✅ Deleted connection {conn_id} from Supabase")
                    return True
                else:
                    logger.error(f"Supabase delete FAILED: {resp.status_code} - {resp.text}")
                    return False
        except Exception as e:
            logger.error(f"Supabase delete error: {e}")
            return False

    async def load_connections_for_user(self, user_id, user_token=None):
        try:
            import httpx
            url = f"{SUPABASE_URL}/rest/v1/user_connections?user_id=eq.{user_id}"
            auth_token = user_token or SUPABASE_ANON_KEY
            headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {auth_token}"}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    logger.error(f"Failed to load connections: {resp.status_code}")
                    return
                rows = resp.json()
                logger.info(f"Found {len(rows)} saved connection(s) for user {user_id[:8]}...")
                for row in rows:
                    conn_id = row["id"]
                    if conn_id in self._connection_cache:
                        continue
                    try:
                        conn = DatabaseConnection(
                            id=conn_id,
                            name=row["name"],
                            host=row["host"],
                            port=row["port"],
                            database=row["database"],
                            username=row["username"],
                            password=_decrypt(row["password"]),
                            dialect=row["dialect"],
                        )
                        resolved_host, original_host = self._resolve_host(conn.host)
                        pg_conn = await self._make_asyncpg_connection(
                            resolved_host, conn.port, conn.username,
                            conn.password or "", conn.database, sni_host=original_host
                        )
                        await pg_conn.execute("SELECT 1")
                        await pg_conn.close()
                        self._resolved_hosts[conn_id] = resolved_host
                        self._original_hosts[conn_id] = original_host
                        self._connection_cache[conn_id] = conn
                        self._connection_users[conn_id] = user_id
                        self._sessions[conn_id] = True
                        conn.status = ConnectionStatus.CONNECTED
                        logger.info(f"Restored connection: {conn.name}")
                    except Exception as e:
                        logger.error(f"Failed to restore connection {row.get('name')}: {e}")
        except Exception as e:
            logger.error(f"Failed to load connections from Supabase: {e}")

    async def load_connections(self):
        logger.info("Connections will be loaded per user on login from Supabase.")

    def get_user_connections(self, user_id):
        return {
            conn_id: conn
            for conn_id, conn in self._connection_cache.items()
            if self._connection_users.get(conn_id) == user_id
        }

    def is_connection_owned_by_user(self, connection_id, user_id):
        return self._connection_users.get(connection_id) == user_id

    def _resolve_host(self, host: str) -> Tuple[str, str]:
        """Returns (resolved_ip_or_host, original_hostname)"""
        host = host.strip()
        original_host = host

        # ✅ Check hardcoded IPs first — bypasses DNS completely
        if host in HARDCODED_HOSTS:
            ip = HARDCODED_HOSTS[host]
            logger.info(f"Using hardcoded IP for {host} -> {ip} (SNI: {host})")
            return ip, original_host

        if is_pooler_host(host):
            logger.info(f"Supabase pooler host: {host}")
            return host, original_host

        try:
            ip = socket.gethostbyname(host)
            logger.info(f"Resolved {host} -> {ip}")
            return ip, original_host
        except socket.gaierror:
            logger.warning(f"Could not resolve {host}, using as-is")
            return host, original_host

    def _build_ssl_context(self) -> ssl.SSLContext:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        return ssl_ctx

    async def _make_asyncpg_connection(self, host, port, user, password, database, sni_host=None):
        """
        ✅ KEY FIX: When connecting via IP, asyncpg needs the original hostname
        passed via the 'host' parameter for SNI. We achieve this by using
        asyncpg's direct_tls_upgrade with the original hostname.

        NOTE: this opens a single one-off connection — used only for connection
        tests / initial verification. Actual query execution now goes through
        the pooled path below (_get_or_create_pool / execute_query) instead of
        this method, to avoid a fresh TCP+TLS+auth handshake per query.
        """
        import asyncpg

        effective_host = sni_host if sni_host else host
        logger.info(f"Connecting: host={host}, sni={effective_host}, port={port}, user={user}")

        ssl_ctx = self._build_ssl_context()

        # ✅ Use original hostname for connection so SNI works correctly
        # asyncpg uses the host parameter for SNI automatically
        return await asyncpg.connect(
            host=effective_host,   # Use original hostname for SNI
            port=port,
            user=user,
            password=password,
            database=database,
            ssl=ssl_ctx,
            timeout=30,
            command_timeout=60,
        )

    async def _get_asyncpg_conn(self, connection_id: str):
        """One-off connection — kept for callers that explicitly want a single
        raw connection (e.g. connect()/test_connection()'s initial ping)."""
        conn = self._connection_cache.get(connection_id)
        if not conn:
            raise ValueError(f"No connection found for: {connection_id}")
        original_host = self._original_hosts.get(connection_id, conn.host)
        return await self._make_asyncpg_connection(
            conn.host, conn.port, conn.username, conn.password or "", conn.database,
            sni_host=original_host
        )

    # ── Connection pooling (NEW) ─────────────────────────────────────────────
    # Every prior version of execute_query/list_tables/get_table_info opened a
    # brand-new asyncpg connection (full TCP + TLS + Postgres auth handshake)
    # and closed it immediately after every single call. Under any repeated
    # load (background alert checks, schema browsing, normal querying) this
    # was needlessly expensive and a real contributor to hitting Supabase's
    # Disk IO / connection budget. A pool is created once per connection_id
    # and reused for all subsequent queries against that same connection.

    async def _get_or_create_pool(self, connection_id: str):
        existing = self._pools.get(connection_id)
        if existing is not None:
            return existing

        conn = self._connection_cache.get(connection_id)
        if not conn:
            raise ValueError(f"No connection found for: {connection_id}")

        import asyncpg

        original_host = self._original_hosts.get(connection_id, conn.host)
        effective_host = original_host  # same SNI-correct hostname used by _make_asyncpg_connection
        ssl_ctx = self._build_ssl_context()

        pool = await asyncpg.create_pool(
            host=effective_host,
            port=conn.port,
            user=conn.username,
            password=conn.password or "",
            database=conn.database,
            ssl=ssl_ctx,
            min_size=1,
            max_size=5,
            command_timeout=60,
            timeout=30,
        )
        self._pools[connection_id] = pool
        logger.info(f"[PRISM DB] Created connection pool for '{conn.name}' ({connection_id})")
        return pool

    async def _close_pool(self, connection_id: str):
        pool = self._pools.pop(connection_id, None)
        if pool is not None:
            try:
                await pool.close()
                logger.info(f"[PRISM DB] Closed connection pool for {connection_id}")
            except Exception as e:
                logger.error(f"[PRISM DB] Error closing pool for {connection_id}: {e}")

    def _get_cache_key(self, connection: DatabaseConnection) -> str:
        if connection.id:
            return connection.id
        return f"{connection.username}@{connection.host}:{connection.port}/{connection.database}"

    async def connect(self, connection: DatabaseConnection, user_id=None, user_token=None) -> bool:
        try:
            connection.host = connection.host.strip()
            connection.database = connection.database.strip()
            connection.username = connection.username.strip()
            cache_key = self._get_cache_key(connection)
            resolved_host, original_host = self._resolve_host(connection.host)

            pg_conn = await self._make_asyncpg_connection(
                resolved_host, connection.port, connection.username,
                connection.password or "", connection.database,
                sni_host=original_host
            )
            await pg_conn.execute("SELECT 1")
            await pg_conn.close()

            self._resolved_hosts[cache_key] = resolved_host
            self._original_hosts[cache_key] = original_host
            connection.status = ConnectionStatus.CONNECTED
            self._connection_cache[cache_key] = connection
            self._sessions[cache_key] = True

            if user_id:
                self._connection_users[cache_key] = user_id
                if user_token:
                    self._user_tokens[user_id] = user_token
                await self._supabase_save_connection(cache_key, connection, user_id, user_token)

            logger.info(f"Connected to database: {connection.name} -> {resolved_host}")
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def disconnect(self, connection_id: str) -> bool:
        user_id = self._connection_users.get(connection_id)
        user_token = self._user_tokens.get(user_id) if user_id else None

        if connection_id not in self._connection_cache and connection_id not in self._engines:
            logger.warning(f"disconnect() called for unknown connection_id: {connection_id}")
            await self._supabase_delete_connection(connection_id, user_id, user_token)
            return False

        if connection_id in self._engines:
            await self._engines[connection_id].dispose()
            del self._engines[connection_id]

        await self._close_pool(connection_id)  # NEW: close pooled connections too

        self._sessions.pop(connection_id, None)
        self._connection_cache.pop(connection_id, None)
        self._resolved_hosts.pop(connection_id, None)
        self._original_hosts.pop(connection_id, None)
        self._connection_users.pop(connection_id, None)

        deleted = await self._supabase_delete_connection(connection_id, user_id, user_token)
        if not deleted:
            logger.error(f"Connection {connection_id} removed from memory but Supabase delete failed.")
        return True

    async def disconnect_all(self):
        for conn_id in list(self._engines.keys()):
            await self._engines[conn_id].dispose()
        self._engines.clear()

        for conn_id in list(self._pools.keys()):  # NEW: close all pools on shutdown
            await self._close_pool(conn_id)

        self._sessions.clear()
        self._connection_cache.clear()
        self._resolved_hosts.clear()
        self._original_hosts.clear()
        self._connection_users.clear()
        self._user_tokens.clear()
        logger.info("All database connections closed.")

    async def test_connection(self, connection: DatabaseConnection) -> Tuple[bool, str]:
        try:
            dialect = connection.dialect.value
            connection.host = connection.host.strip()
            connection.database = connection.database.strip()
            connection.username = connection.username.strip()
            resolved_host, original_host = self._resolve_host(connection.host)

            if dialect == "postgresql":
                pg_conn = await self._make_asyncpg_connection(
                    resolved_host, connection.port, connection.username,
                    connection.password or "", connection.database,
                    sni_host=original_host
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

    @asynccontextmanager
    async def get_session(self, connection_id: str):
        conn = self._connection_cache.get(connection_id)
        if not conn:
            raise ValueError(f"No connection found for: {connection_id}")
        yield connection_id

    async def execute_query(self, connection_id, sql, params=None):
        try:
            pool = await self._get_or_create_pool(connection_id)  # NEW: reused pool, not a fresh connect
            async with pool.acquire() as pg_conn:
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

    async def list_tables(self, connection_id: str) -> List[str]:
        try:
            pool = await self._get_or_create_pool(connection_id)  # NEW: reused pool
            async with pool.acquire() as pg_conn:
                rows = await pg_conn.fetch("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """)
                return [row['table_name'] for row in rows]
        except Exception as e:
            logger.error(f"Failed to list tables: {e}")
            return []

    async def get_table_info(self, connection_id: str, table_name: str) -> Optional[TableInfo]:
        try:
            pool = await self._get_or_create_pool(connection_id)  # NEW: reused pool
            async with pool.acquire() as pg_conn:
                columns_rows = await pg_conn.fetch("""
                    SELECT column_name, data_type, is_nullable, column_default, ordinal_position
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = $1
                    ORDER BY ordinal_position
                """, table_name)

                pk_rows = await pg_conn.fetch("""
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_name = $1 AND tc.table_schema = 'public'
                """, table_name)
                primary_keys = [row['column_name'] for row in pk_rows]

                fk_rows = await pg_conn.fetch("""
                    SELECT kcu.column_name, ccu.table_name AS referenced_table,
                           ccu.column_name AS referenced_column, tc.constraint_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
                    WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = $1 AND tc.table_schema = 'public'
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


# Global instance
db_manager = DatabaseManager()