"""
Report generation service for automated reporting.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..models.database import QueryResponse, ExportFormat, ExportRequest, DatabaseDialect
from ..config import get_settings
from .export_service import export_service
from .database_manager import db_manager

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Automated report generation service.
    Generates scheduled reports from SQL queries.
    """

    def __init__(self):
        self.settings = get_settings()
        self._report_templates: Dict[str, Dict[str, Any]] = {}

    # ==========================================================
    # Template Management
    # ==========================================================

    def register_template(
        self,
        template_id: str,
        name: str,
        description: str,
        connection_id: str,
        sql_query: str,
        schedule: Optional[str] = None,
        recipients: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Register a report template.
        """

        # Basic SQL safety check (Only allow SELECT queries)
        if not sql_query.strip().lower().startswith("select"):
            raise ValueError("Only SELECT queries are allowed for reports.")

        template = {
            "id": template_id,
            "name": name,
            "description": description,
            "connection_id": connection_id,
            "sql_query": sql_query.strip(),
            "schedule": schedule,
            "recipients": recipients or [],
            "created_at": datetime.utcnow().isoformat(),
            "last_run": None,
            "last_status": None,
            "last_error": None,
            "last_file": None,
        }

        self._report_templates[template_id] = template
        logger.info(f"Registered report template: {template_id}")

        return template

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        return self._report_templates.get(template_id)

    def list_templates(self) -> List[Dict[str, Any]]:
        return list(self._report_templates.values())

    def delete_template(self, template_id: str) -> bool:
        if template_id in self._report_templates:
            del self._report_templates[template_id]
            logger.info(f"Deleted report template: {template_id}")
            return True
        return False

    # ==========================================================
    # Report Generation
    # ==========================================================

    async def generate_report(
        self,
        template_id: str,
        format: ExportFormat = ExportFormat.EXCEL,
    ) -> Dict[str, Any]:
        """
        Generate a report from a registered template.
        """

        if template_id not in self._report_templates:
            raise ValueError(f"Template not found: {template_id}")

        template = self._report_templates[template_id]

        try:
            # Execute SQL query
            success, columns, results, error = await db_manager.execute_query(
                connection_id=template["connection_id"],
                sql=template["sql_query"],
            )

            if not success:
                template["last_status"] = "failed"
                template["last_error"] = error

                return {
                    "success": False,
                    "error": error,
                    "template_id": template_id,
                }

            # Build QueryResponse object
            query_response = QueryResponse(
                query_id=f"report_{template_id}_{int(datetime.utcnow().timestamp())}",
                natural_language=f"Report: {template['name']}",
                generated_sql=template["sql_query"],
                explanation=f"Auto-generated report: {template['description']}",
                success=True,
                execution_time_ms=0,
                row_count=len(results),
                columns=columns,
                results=results,
                timestamp=datetime.utcnow(),
            )

            # Prepare export request
            export_request = ExportRequest(
                query_id=query_response.query_id,
                format=format,
                filename=f"report_{template_id}_{datetime.utcnow().strftime('%Y%m%d')}",
                title=template["name"],
                description=template["description"],
            )

            filepath = await export_service.export(export_request, query_response)

            # Update template status
            template["last_run"] = datetime.utcnow().isoformat()
            template["last_status"] = "success"
            template["last_file"] = filepath
            template["last_error"] = None

            logger.info(f"Report generated: {template_id} -> {filepath}")

            return {
                "success": True,
                "filepath": filepath,
                "template_id": template_id,
                "row_count": len(results),
                "columns": columns,
            }

        except Exception as e:
            logger.error(f"Report generation failed: {e}")

            template["last_status"] = "failed"
            template["last_error"] = str(e)

            return {
                "success": False,
                "error": str(e),
                "template_id": template_id,
            }

    # ==========================================================
    # Database Summary Report
    # ==========================================================

    async def generate_summary_report(
        self,
        connection_id: str,
        dialect: DatabaseDialect = DatabaseDialect.POSTGRESQL,
        title: str = "Database Summary Report",
    ) -> Dict[str, Any]:
        """
        Generate a summary report of the database schema.
        """

        from .schema_discovery import schema_discovery

        schema_data = await schema_discovery.discover_full_schema(connection_id)

        summary = {
            "title": title,
            "generated_at": datetime.utcnow().isoformat(),
            "database": {
                "total_tables": schema_data.get("table_count", 0),
                "total_relationships": schema_data.get("relationship_count", 0),
            },
            "tables": [],
        }

        for table in schema_data.get("tables", []):
            table_name = table.get("name", "")

            # Dialect-safe quoting
            if dialect == DatabaseDialect.MYSQL:
                sql = f"SELECT COUNT(*) as cnt FROM `{table_name}`"
            else:
                sql = f'SELECT COUNT(*) as cnt FROM "{table_name}"'

            success, _, results, _ = await db_manager.execute_query(
                connection_id=connection_id,
                sql=sql,
            )

            row_count = results[0].get("cnt", 0) if success and results else 0

            summary["tables"].append({
                "name": table_name,
                "columns": len(table.get("columns", [])),
                "primary_keys": table.get("primary_keys", []),
                "row_count": row_count,
            })

        return summary


# Global instance
report_generator = ReportGenerator()