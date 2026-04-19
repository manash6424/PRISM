import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from backend.config import get_settings
from backend.api.routes import router
from backend.api.auth import auth_router          # ✅ NEW
from backend.services.database_manager import db_manager
from backend.services.schema_discovery import schema_discovery

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"AI Provider: {settings.ai.provider}")

    if not settings.debug and "*" in settings.allowed_hosts:
        logger.warning("CORS wildcard '*' detected in non-debug mode.")

    # Restore all persisted connections on startup
    await db_manager.load_connections()

    yield

    logger.info("Shutting down PRISM...")
    await db_manager.disconnect_all()


app = FastAPI(
    title=settings.app_name,
    description="AI Desktop Copilot - Natural Language to SQL Query Engine",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_hosts,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Register both routers
app.include_router(router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")   # ✅ NEW

from backend.upload_api import router as upload_router
app.include_router(upload_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "documentation": "/docs",
    }


def run_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info" if not settings.debug else "debug",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI Desktop Copilot Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")

    args = parser.parse_args()
    run_server(host=args.host, port=args.port, reload=args.reload)