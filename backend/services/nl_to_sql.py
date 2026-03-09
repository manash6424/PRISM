"""
Natural Language to SQL conversion service.
Uses AI/LLM to convert natural language queries to SQL.
"""

import re
import json
import logging
from typing import Optional, Tuple

from ..models.database import DatabaseDialect
from ..config import get_settings

logger = logging.getLogger(__name__)


class NLToSQLConverter:
    """
    Converts natural language queries to SQL using AI/LLM.
    Supports multiple database dialects and provides explanations.
    """

    def __init__(self):
        self.settings = get_settings()
        self._client = None
        self._client_model = None
        self._ollama_url = None
        self._initialize_client()

    # ==========================================================
    # Client Initialization
    # ==========================================================

    def _initialize_client(self):
        """Initialize AI client based on configuration."""
        provider = (self.settings.ai.provider or "").lower()

        try:
            if provider == "openai":
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self.settings.ai.api_key,
                    base_url=self.settings.ai.base_url or "https://api.openai.com/v1",
                )
                self._client_model = self.settings.ai.model

            elif provider == "anthropic":
                import anthropic
                self._client = anthropic.AsyncAnthropic(
                    api_key=self.settings.ai.api_key,
                    base_url=self.settings.ai.base_url,
                )
                self._client_model = self.settings.ai.model

            elif provider == "groq":
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(
                    api_key=self.settings.ai.api_key,
                    base_url=self.settings.ai.base_url or "https://api.groq.com/openai/v1",
                )
                self._client_model = self.settings.ai.model

            elif provider == "ollama":
                self._client = None
                self._client_model = self.settings.ai.model
                self._ollama_url = (
                    self.settings.ai.base_url or "http://localhost:11434"
                )

            else:
                logger.warning(f"Unknown AI provider: {provider}")

        except ImportError as e:
            logger.error(f"AI provider package not installed: {e}")

    # ==========================================================
    # Public Method
    # ==========================================================

    async def convert(
        self,
        natural_language: str,
        schema_context: str,
        dialect: DatabaseDialect = DatabaseDialect.POSTGRESQL,
        include_explanation: bool = True,
    ) -> Tuple[str, Optional[str]]:
        """
        Convert natural language query to SQL.
        Returns (generated_sql, explanation)
        """

        sql_prompt = self._build_sql_prompt(natural_language, schema_context, dialect)
        provider = (self.settings.ai.provider or "").lower()

        try:
            if provider in ("openai", "groq"):
                sql = await self._get_completion(sql_prompt)
            elif provider == "anthropic":
                sql = await self._get_completion_anthropic(sql_prompt)
            elif provider == "ollama":
                sql = await self._get_completion_ollama(sql_prompt)
            else:
                sql, explanation = self._rule_based_conversion(natural_language, schema_context, dialect)
                return sql, explanation

            # Clean the SQL
            sql = self._clean_sql(sql)

            # Generate explanation separately if needed
            explanation = None
            if include_explanation:
                explanation = self._generate_explanation(sql)

            return sql, explanation

        except Exception as e:
            logger.error(f"NL to SQL conversion failed: {e}")
            raise

    # ==========================================================
    # Prompt Builder
    # ==========================================================

    def _build_sql_prompt(
        self,
        natural_language: str,
        schema_context: str,
        dialect: DatabaseDialect,
    ) -> str:
        """Build prompt that returns plain SQL only."""

        dialect_instructions = {
            DatabaseDialect.POSTGRESQL: """
PostgreSQL Specific Rules:
- Use LIMIT instead of TOP
- Use ILIKE for case-insensitive matching
- Use EXTRACT(YEAR FROM date) for year extraction
- Use COALESCE for null handling
- Use TRUE/FALSE for booleans
""",
            DatabaseDialect.MYSQL: """
MySQL Specific Rules:
- Use LIMIT for limiting rows
- Use YEAR(date) for year extraction
- Use IFNULL for null handling
- Use 1/0 for booleans
""",
        }

        return f"""You are an expert SQL query generator.

CRITICAL INSTRUCTIONS:
- Return ONLY the raw SQL query
- Do NOT include markdown code blocks (no ``` or ```sql)
- Do NOT include JSON
- Do NOT include any explanation or commentary
- Just the plain SQL statement ending with a semicolon

{dialect_instructions.get(dialect, "")}

Database Schema:
{schema_context}

Natural Language Query: {natural_language}

SQL Query:"""

    # ==========================================================
    # AI Completions
    # ==========================================================

    async def _get_completion(self, prompt: str) -> str:
        """Get completion from OpenAI/Groq."""
        response = await self._client.chat.completions.create(
            model=self._client_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert SQL generator. Return ONLY plain SQL queries with no markdown, no code blocks, no JSON, no explanation.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        return response.choices[0].message.content

    async def _get_completion_anthropic(self, prompt: str) -> str:
        """Get completion from Anthropic."""
        response = await self._client.messages.create(
            model=self._client_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    async def _get_completion_ollama(self, prompt: str) -> str:
        """Get completion from Ollama."""
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._client_model,
                    "prompt": prompt,
                    "stream": False,
                },
            )
        data = response.json()
        return data.get("response", "")

    # ==========================================================
    # SQL Cleaner
    # ==========================================================

    def _clean_sql(self, sql: str) -> str:
        """Strip markdown, JSON, and extra whitespace from SQL."""
        if not sql:
            return ""

        sql = sql.strip()

        # Strip markdown code blocks
        sql = re.sub(r"```(?:sql|SQL)?\s*", "", sql)
        sql = re.sub(r"```", "", sql)

        # If it looks like JSON, try to extract sql field
        if sql.strip().startswith("{"):
            try:
                parsed = json.loads(sql)
                sql = parsed.get("sql", sql)
            except json.JSONDecodeError:
                pass

        # Remove any leading/trailing non-SQL text
        # Keep only from first SQL keyword
        sql_match = re.search(
            r"(SELECT|INSERT|UPDATE|DELETE|WITH|SHOW|DESCRIBE|EXPLAIN)\b",
            sql,
            re.IGNORECASE,
        )
        if sql_match:
            sql = sql[sql_match.start():]

        return sql.strip()

    # ==========================================================
    # Explanation Generator
    # ==========================================================

    def _generate_explanation(self, sql: str) -> str:
        """Generate a simple explanation from SQL."""
        if not sql:
            return "No query generated."

        sql_upper = sql.upper()
        parts = []

        if "SELECT" in sql_upper:
            parts.append("Retrieves data from the database.")
        if "WHERE" in sql_upper:
            parts.append("Filters results based on conditions.")
        if "JOIN" in sql_upper:
            parts.append("Combines data from multiple tables.")
        if "GROUP BY" in sql_upper:
            parts.append("Groups results by specific columns.")
        if "ORDER BY" in sql_upper:
            parts.append("Sorts the results.")
        if "LIMIT" in sql_upper:
            parts.append("Limits the number of results returned.")

        return " ".join(parts) if parts else "SQL query generated successfully."

    # ==========================================================
    # Fallback Rule-Based
    # ==========================================================

    def _rule_based_conversion(
        self,
        natural_language: str,
        schema_context: str,
        dialect: DatabaseDialect,
    ) -> Tuple[str, Optional[str]]:

        nl = natural_language.lower()

        if "all" in nl and "from" in nl:
            table = nl.split("from")[-1].strip()
            sql = f"SELECT * FROM {table};"
            return sql, "Basic SELECT * query generated using rule-based fallback."

        return (
            "-- Unable to generate SQL using rule-based fallback.",
            "AI provider not configured. Using fallback logic.",
        )


# ==========================================================
# Global instance
# ==========================================================
nl_to_sql = NLToSQLConverter()