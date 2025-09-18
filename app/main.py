import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.config import settings
from app.ingestion.router import router as ingestion_router
from app.ingestion.batch_processor import batch_processor
from app.ingestion.otel_collector import otel_collector_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting VM API application...")

    try:
        await batch_processor.start()
        logger.info("Batch processor started")

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
            await batch_processor.stop()
            logger.info("Batch processor stopped")

            await otel_collector_server.stop()
            logger.info("OpenTelemetry collector stopped")

            logger.info("All services stopped successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

app.include_router(ingestion_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "message": "VM API backend is running!",
    }




