import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routers.routers import api_router
from app.core.config import settings
from app.core.database import init_database
from app.core.metrics import setup_metrics, push_metrics_to_gateway
from app.github.webhook.router import limiter

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
    metrics_task = None

    try:
        # Initialize database
        await init_database()
        logger.info("Database initialized")

        # Start SQS worker
        await worker.start()
        logger.info("SQS worker started")

        # Start metrics push background task
        import asyncio
        metrics_task = asyncio.create_task(push_metrics_to_gateway())
        logger.info("Metrics push task started")

        logger.info("All services started successfully")
        yield

    except Exception:
        logger.exception("Failed to start services")
        raise
    finally:
        logger.info("Shutting down VM API application...")

        try:
            # Stop metrics push task
            if metrics_task:
                metrics_task.cancel()
                try:
                    await metrics_task
                except asyncio.CancelledError:
                    pass
                logger.info("Metrics push task stopped")

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

# Add rate limiter state
app.state.limiter = limiter

# Add rate limit exceeded handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

# Setup Prometheus metrics BEFORE including routers
instrumentator = setup_metrics(app)

# Include all API routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    try:
        return {
            "fastAPI server": {"status": "healthy"},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
