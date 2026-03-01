"""
Schema discovery service for automatic database structure detection.
Identifies tables, relationships, and provides schema context for AI.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from ..models.database import (
    TableInfo,
    DatabaseDialect,
)
from .database_manager import db_manager

logger = logging.getLogger(__name__)


class SchemaDiscovery:
    """
    Automatic schema discovery service that analyzes database structure
    and provides comprehensive schema context for AI queries.
    """

    CACHE_TTL_SECONDS = 3600  # 1 hour

    def __init__(self):
        self._schema_cache: Dict[str, Dict[str, Any]] = {}

    async def discover_full_schema(
        self,
        connection_id: str,
        schema: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Perform full schema discovery on a database.
        """
        cache_key = f"{connection_id}:{schema or 'default'}"

        # Return cached schema if valid
        if not force_refresh and cache_key in self._schema_cache:
            cached = self._schema_cache[cache_key]
            if (
                datetime.utcnow() - cached["timestamp"]
            ).total_seconds() < self.CACHE_TTL_SECONDS:
                logger.info("Returning cached schema")
                return cached["schema"]

        try:
            tables = await db_manager.list_tables(connection_id, schema)

            table_infos: List[TableInfo] = []
            relationships: List[Dict[str, Any]] = []

            for table_name in tables:
                table_info = await db_manager.get_table_info(
                    connection_id, table_name
                )

                if not table_info:
                    continue

                table_infos.append(table_info)

                # Safely handle foreign keys
                for fk in (table_info.foreign_keys or []):
                    relationships.append(
                        {
                            "from_table": table_name,
                            "from_column": fk.column,
                            "to_table": fk.referenced_table,
                            "to_column": fk.referenced_column,
                            "relationship_type": "many_to_one",
                        }
                    )

            schema_data = {
                "tables": [t.model_dump() for t in table_infos],
                "relationships": relationships,
                "table_count": len(table_infos),
                "relationship_count": len(relationships),
                "discovered_at": datetime.utcnow().isoformat(),
            }

            # Cache result
            self._schema_cache[cache_key] = {
                "schema": schema_data,
                "timestamp": datetime.utcnow(),
            }

            logger.info(
                f"Schema discovery complete: {len(table_infos)} tables, "
                f"{len(relationships)} relationships"
            )

            return schema_data

        except Exception as e:
            logger.exception("Schema discovery failed")
            raise e

    def generate_schema_context(
        self,
        schema_data: Dict[str, Any],
        dialect: DatabaseDialect = DatabaseDialect.POSTGRESQL,
    ) -> str:
        """
        Generate formatted schema context for AI prompt usage.
        """
        lines = [
            f"Database Schema Information ({dialect.value}):",
            f"Total Tables: {schema_data.get('table_count', 0)}",
            f"Total Relationships: {schema_data.get('relationship_count', 0)}",
            "",
            "=== TABLES ===",
        ]

        for table in schema_data.get("tables", []):
            table_name = table.get("name", "unknown")
            columns = table.get("columns", [])
            primary_keys = table.get("primary_keys", [])

            lines.append(f"\nTable: {table_name}")

            if primary_keys:
                lines.append(f"  Primary Key: {', '.join(primary_keys)}")

            lines.append("  Columns:")
            for col in columns:
                col_name = col.get("name", "")
                col_type = col.get("data_type", "")
                nullable = "NULL" if col.get("is_nullable") else "NOT NULL"
                pk_flag = " [PK]" if col.get("is_primary_key") else ""

                lines.append(
                    f"    - {col_name}: {col_type} ({nullable}){pk_flag}"
                )

        relationships = schema_data.get("relationships", [])
        if relationships:
            lines.append("\n=== RELATIONSHIPS ===")
            for rel in relationships:
                lines.append(
                    f"  {rel['from_table']}.{rel['from_column']} -> "
                    f"{rel['to_table']}.{rel['to_column']}"
                )

        return "\n".join(lines)

    def get_table_suggestions(
        self, schema_data: Dict[str, Any], query: str
    ) -> List[str]:
        """
        Suggest relevant tables based on natural language query.
        """
        query_lower = query.lower()
        suggestions = []

        keywords = {
            "user": ["users", "customers", "accounts", "profiles"],
            "order": ["orders", "purchases", "transactions"],
            "product": ["products", "items", "inventory", "merchandise"],
            "sale": ["sales", "revenue", "transactions"],
            "report": ["reports", "analytics", "metrics"],
        }

        for key, patterns in keywords.items():
            if key in query_lower:
                for table in schema_data.get("tables", []):
                    table_name = table.get("name", "").lower()
                    if any(pattern in table_name for pattern in patterns):
                        suggestions.append(table["name"])

        # Remove duplicates
        suggestions = list(set(suggestions))

        # Fallback to first 5 tables if no matches
        if not suggestions:
            suggestions = [
                t["name"]
                for t in schema_data.get("tables", [])[:5]
            ]

        return suggestions[:5]

    async def get_table_by_name(
        self, connection_id: str, table_name: str
    ) -> Optional[TableInfo]:
        """
        Get information about a specific table.
        """
        return await db_manager.get_table_info(
            connection_id, table_name
        )

    def clear_cache(self, connection_id: Optional[str] = None):
        """
        Clear schema cache.
        """
        if connection_id:
            keys_to_remove = [
                k for k in self._schema_cache if k.startswith(connection_id)
            ]
            for key in keys_to_remove:
                del self._schema_cache[key]
        else:
            self._schema_cache.clear()

        logger.info("Schema cache cleared")


# Global instance
schema_discovery = SchemaDiscovery()