import os
from typing import Optional
from pydantic import BaseModel, Field
from functools import lru_cache
from dotenv import load_dotenv

# Load .env file automatically
load_dotenv()

class DatabaseConfig(BaseModel):
    host: str = Field(default="localhost")
    port: int = Field(default=5432, ge=1, le=65535)
    username: str = Field(default="postgres")
    password: str = Field(default="")
    name: str = Field(default="postgres", min_length=1)
    dialect: str = Field(default="postgresql")
    ssl_mode: Optional[str] = Field(default=None)

    @property
    def connection_string(self) -> str:
        if self.ssl_mode and self.ssl_mode.lower() != "disable":
            return f"{self.dialect}://{self.username}:{self.password}@{self.host}:{self.port}/{self.name}?sslmode={self.ssl_mode}"
        return f"{self.dialect}://{self.username}:{self.password}@{self.host}:{self.port}/{self.name}"

class AIConfig(BaseModel):
    provider: str = Field(default="openai")
    api_key: str = Field(default="")
    model: str = Field(default="gpt-4")
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2000, ge=1)
    base_url: Optional[str] = Field(default=None)

class AlertConfig(BaseModel):
    email_enabled: bool = Field(default=False)
    smtp_host: Optional[str] = Field(default=None)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: Optional[str] = Field(default=None)
    smtp_password: Optional[str] = Field(default=None)
    slack_enabled: bool = Field(default=False)
    slack_webhook_url: Optional[str] = Field(default=None)
    slack_channel: Optional[str] = Field(default=None)

class ExportConfig(BaseModel):
    export_dir: str = Field(default="./exports")
    pdf_engine: str = Field(default="reportlab")
    max_rows_export: int = Field(default=100000)

class Settings(BaseModel):
    app_name: str = Field(default="AI Desktop Copilot")
    app_version: str = Field(default="1.0.0")
    debug: bool = Field(default=False)
    secret_key: str = Field(default="your-secret-key-change-in-production-32c", min_length=32)
    allowed_hosts: list[str] = Field(default=["*"])
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)

    # Razorpay
    razorpay_key_id: str = Field(default="")
    razorpay_key_secret: str = Field(default="")
    razorpay_webhook_secret: str = Field(default="")

    # Supabase                        ← NEW
    supabase_url: str = Field(default="")
    supabase_service_key: str = Field(default="")


def load_settings() -> Settings:
    ssl_mode = os.getenv("DB_SSL_MODE")
    if ssl_mode and ssl_mode.lower() == "disable":
        ssl_mode = None

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
            pdf_engine=os.getenv("PDF_ENGINE", "reportlab"),
            max_rows_export=int(os.getenv("MAX_ROWS_EXPORT", "100000")),
        ),
        # Razorpay
        razorpay_key_id=os.getenv("RAZORPAY_KEY_ID", ""),
        razorpay_key_secret=os.getenv("RAZORPAY_KEY_SECRET", ""),
        razorpay_webhook_secret=os.getenv("RAZORPAY_WEBHOOK_SECRET", ""),
        # Supabase                        ← NEW
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_service_key=os.getenv("SUPABASE_SERVICE_KEY", ""),
    )


def get_settings() -> Settings:
    return load_settings()


# Singleton for direct import: `from backend.config import settings`   ← NEW
settings = load_settings()