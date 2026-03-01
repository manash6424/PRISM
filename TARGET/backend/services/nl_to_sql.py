"""
Natural Language to SQL conversion service.
Uses AI/LLM to convert natural language queries to SQL.
"""

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
                # Local Ollama instance
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

        prompt = self._build_prompt(natural_language, schema_context, dialect)

        provider = (self.settings.ai.provider or "").lower()

        try:
            if provider == "openai":
                return await self._convert_with_openai(prompt, include_explanation)

            elif provider == "anthropic":
                return await self._convert_with_anthropic(prompt, include_explanation)

            elif provider == "groq":
                return await self._convert_with_openai(prompt, include_explanation)

            elif provider == "ollama":
                return await self._convert_with_ollama(prompt, include_explanation)

            else:
                return self._rule_based_conversion(
                    natural_language, schema_context, dialect
                )

        except Exception as e:
            logger.error(f"NL to SQL conversion failed: {e}")
            raise

    # ==========================================================
    # Prompt Builder
    # ==========================================================

    def _build_prompt(
        self,
        natural_language: str,
        schema_context: str,
        dialect: DatabaseDialect,
    ) -> str:
        """Build structured prompt for AI conversion."""

        dialect_instructions = {
            DatabaseDialect.POSTGRESQL: """
PostgreSQL Specific:
- Use LIMIT instead of TOP
- Use ILIKE for case-insensitive matching
- Use EXTRACT(YEAR FROM date) for year extraction
- Use COALESCE for null handling
- PostgreSQL uses TRUE/FALSE for booleans
""",
            DatabaseDialect.MYSQL: """
MySQL Specific:
- Use LIMIT for limiting rows
- Use LIKE for case-insensitive matching
- Use YEAR(date) for year extraction
- Use IFNULL for null handling
- MySQL uses 1/0 for booleans
""",
        }

        return f"""
You are an expert SQL query generator.

Your task:
1. Convert the natural language query into valid SQL.
2. Use ONLY tables and columns from the schema.
3. Follow the specified SQL dialect strictly.
4. Do not hallucinate columns or tables.

{dialect_instructions.get(dialect, "")}

Database Schema:
{schema_context}

Natural Language Query:
{natural_language}

Return output in JSON format:
{{
    "sql": "<generated_sql>",
    "explanation": "<brief explanation>"
}}
"""

    # ==========================================================
    # OpenAI
    # ==========================================================

    async def _convert_with_openai(
        self, prompt: str, include_explanation: bool
    ) -> Tuple[str, Optional[str]]:

        response = await self._client.chat.completions.create(
            model=self._client_model,
            messages=[
                {"role": "system", "content": "You generate SQL queries."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )

        content = response.choices[0].message.content
        return self._parse_llm_response(content, include_explanation)

    # ==========================================================
    # Anthropic
    # ==========================================================

    async def _convert_with_anthropic(
        self, prompt: str, include_explanation: bool
    ) -> Tuple[str, Optional[str]]:

        response = await self._client.messages.create(
            model=self._client_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text
        return self._parse_llm_response(content, include_explanation)

    # ==========================================================
    # Ollama (Local)
    # ==========================================================

    async def _convert_with_ollama(
        self, prompt: str, include_explanation: bool
    ) -> Tuple[str, Optional[str]]:

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
        return self._parse_llm_response(data.get("response", ""), include_explanation)

    # ==========================================================
    # LLM Response Parser
    # ==========================================================

    def _parse_llm_response(
        self, content: str, include_explanation: bool
    ) -> Tuple[str, Optional[str]]:

        try:
            parsed = json.loads(content)
            sql = parsed.get("sql", "").strip()
            explanation = parsed.get("explanation")

            if not include_explanation:
                explanation = None

            return sql, explanation

        except json.JSONDecodeError:
            # Fallback if model didn't return JSON
            return content.strip(), None

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
            explanation = "Basic SELECT * query generated using rule-based fallback."
            return sql, explanation

        return (
            "-- Unable to generate SQL using rule-based fallback.",
            "AI provider not configured. Using fallback logic.",
        )

# ==========================================================
# Create a single global instance to be imported
# ==========================================================
nl_to_sql = NLToSQLConverter()