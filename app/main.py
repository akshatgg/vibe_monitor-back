import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.routers import api_router
from app.core.config import settings
from app.core.database import init_database
from app.ingestion.batch_processor import batch_processor
from app.ingestion.otel_collector import otel_collector_server
from app.ingestion.service import ingestion_service
from app.query.router import router as query_router
from worker import RCAOrchestratorWorker
from app.services.sqs.client import sqs_client


# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown lifecycle for all services.
    
    On startup, initializes the database and starts the batch processor, OpenTelemetry collector, and SQS worker, then yields control for the application to run. On shutdown, stops the SQS worker, stops the batch processor, stops the OpenTelemetry collector, and closes the SQS client. If startup fails, the exception is logged and re-raised; errors during shutdown are logged.
    """
    logger.info("Starting VM API application...")

    worker = RCAOrchestratorWorker()

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

        # Start SQS worker
        await worker.start()
        logger.info("SQS worker started")

        logger.info("All services started successfully")
        yield

    except Exception:
        logger.exception(f"Failed to start services")
        raise
    finally:
        logger.info("Shutting down VM API application...")

        try:
            # Stop SQS worker
            await worker.stop()
            logger.info("SQS worker stopped")

            # Stop batch processor
            await batch_processor.stop()
            logger.info("Batch processor stopped")

            # Stop OpenTelemetry collector
            await otel_collector_server.stop()
            logger.info("OpenTelemetry collector stopped")

            # Close SQS client
            await sqs_client.close()
            logger.info("SQS client closed")

            logger.info("All services stopped successfully")
        except Exception:
            logger.exception(f"Error during shutdown")


# Create FastAPI application
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,  
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

# Include all API routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(query_router, prefix=f"{settings.API_V1_PREFIX}/query")

@app.get("/health")
async def health_check():
    try:
        stats = await ingestion_service.get_ingestion_stats()
        return {
            "fastAPI server": {
                "status":"healthy"
            },
            "clickhouse": {
                "status": "healthy" if stats.clickhouse_health else "unhealthy",
                "connected": stats.clickhouse_health
            },
            "otel": {
                "collector_status": stats.otel_collector_status,
                "batch_processor": {
                    "running": stats.batch_processor_stats.get("running", False),
                    "pending_logs": stats.batch_processor_stats.get("total_pending_logs", 0),
                }
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")