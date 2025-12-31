from contextlib import asynccontextmanager
from dotenv import load_dotenv
import logging
import sentry_sdk
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routers.routers import api_router
from app.core.config import settings
from app.core.database import init_database
from app.core.logging_config import configure_logging
from app.middleware import RequestIDMiddleware
from app.github.webhook.router import limiter
from app.core.otel_config import setup_otel_metrics, setup_otel_logs, shutdown_otel
from app.core.otel_metrics import init_meter
from app.worker import RCAOrchestratorWorker
from app.services.sqs.client import sqs_client
from app.core.redis import close_redis, get_redis


# Load environment variables
load_dotenv()

# Configure logging with request_id and job_id support using stdlib logging
configure_logging()

# Get logger for this module
logger = logging.getLogger(__name__)

# Initialize Sentry for error tracking
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=1.0 if settings.is_local else 0.1,
        environment=settings.ENVIRONMENT,
        send_default_pii=False,
        enable_logs=True,
    )
    logger.info("Sentry initialized")

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

        # Validate Redis connection (for web chat SSE streaming)
        if not settings.REDIS_URL:
            logger.warning("REDIS_URL not configured - web chat will be unavailable")
        else:
            try:
                redis_client = await get_redis()
                await redis_client.ping()
                logger.info("Redis connection validated")
            except Exception as e:
                logger.error(f"Redis connection failed: {e}")

        # Initialize OpenTelemetry (if enabled)
        if settings.OTEL_ENABLED and settings.OTEL_OTLP_ENDPOINT:
            try:
                # Setup metrics
                meter_provider = setup_otel_metrics(settings.OTEL_OTLP_ENDPOINT)
                init_meter(meter_provider.get_meter("vm-api"))
                logger.info(
                    f"OpenTelemetry metrics configured: {settings.OTEL_OTLP_ENDPOINT}"
                )

                # Setup logs
                otel_log_handler = setup_otel_logs(settings.OTEL_OTLP_ENDPOINT)
                configure_logging(otel_handler=otel_log_handler)
                logger.info("OpenTelemetry logs configured")
            except Exception as e:
                logger.error(f"Failed to initialize OpenTelemetry: {e}")

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
            # Shutdown OpenTelemetry first (flush remaining data)
            if settings.OTEL_ENABLED:
                shutdown_otel()
                logger.info("OpenTelemetry shutdown complete")

            # Stop SQS worker
            await worker.stop()
            logger.info("SQS worker stopped")

            # Close SQS client
            await sqs_client.close()
            logger.info("SQS client closed")

            # Close Redis client
            await close_redis()
            logger.info("Redis client closed")

            logger.info("All services stopped successfully")
        except Exception:
            logger.exception("Error during shutdown")


# Create FastAPI application
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    openapi_url="/openapi.json" if settings.is_local else None,
)

# Add rate limiter state
app.state.limiter = limiter

# Add rate limit exceeded handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add Request ID middleware (must be added first to ensure request_id is available)
app.add_middleware(RequestIDMiddleware)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

# Instrument FastAPI with OpenTelemetry
if settings.OTEL_ENABLED:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumented with OpenTelemetry")
    except Exception as e:
        logger.error(f"Failed to instrument FastAPI with OpenTelemetry: {e}")

# Include all API routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# Mount static files for assets (logos, images, etc.)
app.mount("/assets", StaticFiles(directory="assets"), name="assets")


@app.get("/health")
async def health_check():
    try:
        return {
            "fastAPI server": {"status": "healthy"},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
