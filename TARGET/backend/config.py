import os
from typing import Optional
from pydantic import BaseModel, Field
from functools import lru_cache
from dotenv import load_dotenv

# Load .env file automatically
load_dotenv()

class DatabaseConfig(BaseModel):
    """Database connection configuration."""
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    username: str = Field(default="postgres", description="Database username")
    password: str = Field(default="", description="Database password")
    name: str = Field(default="postgres", min_length=1, description="Database name")
    dialect: str = Field(default="postgresql", description="Database dialect")
    ssl_mode: Optional[str] = Field(default=None, description="SSL mode")

    @property
    def connection_string(self) -> str:
        """Generate SQLAlchemy connection string."""
        if self.ssl_mode and self.ssl_mode.lower() != "disable":
            return f"{self.dialect}://{self.username}:{self.password}@{self.host}:{self.port}/{self.name}?sslmode={self.ssl_mode}"
        return f"{self.dialect}://{self.username}:{self.password}@{self.host}:{self.port}/{self.name}"

class AIConfig(BaseModel):
    """AI/LLM configuration for natural language processing."""
    provider: str = Field(default="openai", description="AI provider (openai, anthropic)")
    api_key: str = Field(default="", description="API key for AI service")
    model: str = Field(default="gpt-4", description="Model to use")
    temperature: float = Field(default=0.1, ge=0.0, le=1.0, description="Temperature for generation")
    max_tokens: int = Field(default=2000, ge=1, description="Max tokens in response")
    base_url: Optional[str] = Field(default=None, description="Custom base URL for API")

class AlertConfig(BaseModel):
    """Alert configuration for notifications."""
    email_enabled: bool = Field(default=False, description="Enable email alerts")
    smtp_host: Optional[str] = Field(default=None, description="SMTP host")
    smtp_port: int = Field(default=587, ge=1, le=65535, description="SMTP port")
    smtp_user: Optional[str] = Field(default=None, description="SMTP username")
    smtp_password: Optional[str] = Field(default=None, description="SMTP password")
    slack_enabled: bool = Field(default=False, description="Enable Slack alerts")
    slack_webhook_url: Optional[str] = Field(default=None, description="Slack webhook URL")
    slack_channel: Optional[str] = Field(default=None, description="Default Slack channel")

class ExportConfig(BaseModel):
    """Export configuration for reports and data."""
    export_dir: str = Field(default="./exports", description="Directory for export files")
    pdf_engine: str = Field(default="weasyprint", description="PDF generation engine")
    max_rows_export: int = Field(default=100000, description="Max rows for export")

class Settings(BaseModel):
    """Main application settings."""
    app_name: str = Field(default="AI Desktop Copilot")
    app_version: str = Field(default="1.0.0")
    debug: bool = Field(default=False, description="Debug mode")
    secret_key: str = Field(default="your-secret-key-change-in-production-32c", min_length=32, description="Secret key for encryption")
    allowed_hosts: list[str] = Field(default=["*"], description="Allowed CORS hosts")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)

def load_settings() -> Settings:
    """Load settings from environment variables."""
    # Handle ssl_mode — "disable" means no SSL, convert to None
    ssl_mode = os.getenv("DB_SSL_MODE")
    if ssl_mode and ssl_mode.lower() == "disable":
        ssl_mode = None

    # Handle empty base_url
    base_url = os.getenv("AI_BASE_URL")
    if not base_url:
        base_url = None

    return Settings(
        app_name=os.getenv("APP_NAME", "AI Desktop Copilot"),
        app_version=os.getenv("APP_VERSION", "1.0.0"),
        debug=os.getenv("DEBUG", "false").lower() == "true",
        secret_key=os.getenv("SECRET_KEY", "your-secret-key-change-in-production-32c"),
        allowed_hosts=os.getenv("ALLOWED_HOSTS", "*").split(","),
        database=DatabaseConfig(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            username=os.getenv("DB_USERNAME", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            name=os.getenv("DB_NAME", "postgres"),
            dialect=os.getenv("DB_DIALECT", "postgresql"),
            ssl_mode=ssl_mode,
        ),
        ai=AIConfig(
            provider=os.getenv("AI_PROVIDER", "openai"),
            api_key=os.getenv("AI_API_KEY", ""),
            model=os.getenv("AI_MODEL", "gpt-4"),
            temperature=float(os.getenv("AI_TEMPERATURE", "0.1")),
            max_tokens=int(os.getenv("AI_MAX_TOKENS", "2000")),
            base_url=base_url,
        ),
        alerts=AlertConfig(
            email_enabled=os.getenv("EMAIL_ENABLED", "false").lower() == "true",
            smtp_host=os.getenv("SMTP_HOST"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER"),
            smtp_password=os.getenv("SMTP_PASSWORD"),
            slack_enabled=os.getenv("SLACK_ENABLED", "false").lower() == "true",
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
            slack_channel=os.getenv("SLACK_CHANNEL"),
        ),
        export=ExportConfig(
            export_dir=os.getenv("EXPORT_DIR", "./exports"),
            pdf_engine=os.getenv("PDF_ENGINE", "weasyprint"),
            max_rows_export=int(os.getenv("MAX_ROWS_EXPORT", "100000")),
        ),
    )

@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return load_settings()
