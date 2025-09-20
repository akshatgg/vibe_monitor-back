import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from app.api.routers.routers import api_router
from app.core.database import init_database
from app.core.config import settings
from app.query.router import router as query_router
from app.ingestion.batch_processor import batch_processor
from app.ingestion.otel_collector import otel_collector_server

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Unified lifespan manager for all application services"""
    logger.info("Starting VM API application...")

    try:
        # Initialize database
        await init_database()
        logger.info("Database initialized")

        # Start batch processor
        await batch_processor.start()
        logger.info("Batch processor started")

        # Start OpenTelemetry collector
        await otel_collector_server.start()
        logger.info("OpenTelemetry collector started")

        logger.info("All services started successfully")
        yield

    except Exception as e:
        logger.error(f"Failed to start services: {e}")
        raise
    finally:
        logger.info("Shutting down VM API application...")

        try:
            # Stop batch processor
            await batch_processor.stop()
            logger.info("Batch processor stopped")

            # Stop OpenTelemetry collector
            await otel_collector_server.stop()
            logger.info("OpenTelemetry collector stopped")

            logger.info("All services stopped successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


# Create FastAPI application
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

# Include all API routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(query_router, prefix=f"{settings.API_V1_PREFIX}/query")

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "FastAPI backend is running!"}

