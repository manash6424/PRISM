# backend/main.py
from dotenv import load_dotenv
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from backend.config import get_settings
from backend.api.routes import router
from backend.services.database_manager import db_manager
from backend.services.schema_discovery import schema_discovery

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"AI Provider: {settings.ai.provider}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down AI Desktop Copilot...")
    
    # Close all database connections
    for conn_id in list(db_manager._engines.keys()):
        await db_manager.disconnect(conn_id)


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="AI Desktop Copilot - Natural Language to SQL Query Engine",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
   allow_origins=settings.allowed_hosts,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "documentation": "/docs",
    }


def run_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """Run the application server."""
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
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    
    args = parser.parse_args()
    
    run_server(host=args.host, port=args.port, reload=args.reload)