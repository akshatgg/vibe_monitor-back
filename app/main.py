import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.routers import api_router
from app.core.config import settings
from app.core.database import init_database
from app.metrics.router import router as metrics_router
from app.log.router import router as log_router
from app.grafana.router import router as grafana_router

from app.worker import RCAOrchestratorWorker
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

    On startup, initializes the database and starts the SQS worker, then yields control for the application to run. On shutdown, stops the SQS worker, and closes the SQS client. If startup fails, the exception is logged and re-raised; errors during shutdown are logged.
    """
    logger.info("Starting VM API application...")

    worker = RCAOrchestratorWorker()

    try:
        # Initialize database
        await init_database()
        logger.info("Database initialized")

        # Start SQS worker
        await worker.start()
        logger.info("SQS worker started")

        logger.info("All services started successfully")
        yield

    except Exception:
        logger.exception("Failed to start services")
        raise
    finally:
        logger.info("Shutting down VM API application...")

        try:
            # Stop SQS worker
            await worker.stop()
            logger.info("SQS worker stopped")

            # Close SQS client
            await sqs_client.close()
            logger.info("SQS client closed")

            logger.info("All services stopped successfully")
        except Exception:
            logger.exception("Error during shutdown")


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
app.include_router(metrics_router, prefix=settings.API_V1_PREFIX)
app.include_router(log_router, prefix=settings.API_V1_PREFIX)
app.include_router(grafana_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    try:
        return {
            "fastAPI server": {"status": "healthy"},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
