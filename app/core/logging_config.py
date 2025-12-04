"""
Centralized logging configuration with request_id and job_id context support using loguru.

This module configures loguru to intercept all standard logging calls and provides
automatic context propagation using contextvars. Also supports OpenTelemetry log export.
"""

import json
import logging
import sys
from contextvars import ContextVar
from types import FrameType
import traceback
from typing import Optional

from loguru import logger

from app.core.config import settings

# Context variables for request_id and job_id
# These are thread-safe and async-safe context variables
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
job_id_var: ContextVar[str] = ContextVar("job_id", default="-")


class InterceptHandler(logging.Handler):
    """
    Handler that intercepts standard logging calls and redirects them to loguru.

    This ensures all existing logging.getLogger() calls throughout the codebase
    work seamlessly with loguru without requiring code changes.
    """

    def emit(self, record: logging.LogRecord):
        """Intercept standard logging record and pass to loguru."""
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where the logging call originated
        from app.core.config import settings

        frame: Optional[FrameType] = sys._getframe(settings.LOGGING_FRAME_DEPTH)
        depth: int = settings.LOGGING_FRAME_DEPTH

        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def context_filter(record):
    """
    Filter that adds request_id and job_id from contextvars to log records.

    This allows all logs within a request/job to automatically include the context
    without needing to manually bind the logger everywhere.
    """
    # Set request_id only if not empty or default "-"
    request_id = request_id_var.get()
    if request_id and request_id != "-":
        record["extra"]["request_id"] = request_id

    # Set job_id only if not empty or default "-"
    job_id = job_id_var.get()
    if job_id and job_id != "-":
        record["extra"]["job_id"] = job_id

    return record


def build_simplified_json_record(record):
    """
    Build a simplified JSON log record from a loguru record.

    Only includes essential fields:
    - timestamp
    - level
    - message
    - request_id (if present)
    - job_id (if present)
    - exception (if present)
    - process info
    - thread info
    """
    log_record = {
        "timestamp": record["time"].strftime("%Y-%m-%d %H:%M:%S"),
        "level": record["level"].name,
        "message": record["message"],
    }

    # Add request_id if present
    if "request_id" in record["extra"]:
        log_record["request_id"] = record["extra"]["request_id"]

    # Add job_id if present
    if "job_id" in record["extra"]:
        log_record["job_id"] = record["extra"]["job_id"]

    # Add exception if present
    if record["exception"]:
        traceback_text = None
        if record["exception"].traceback:
            try:
                traceback_text = "".join(
                    traceback.format_exception(
                        record["exception"].type,
                        record["exception"].value,
                        record["exception"].traceback,
                    )
                ).strip()
            except Exception:
                # Fall back to stringifying the traceback object if formatting fails
                traceback_text = str(record["exception"].traceback)

        log_record["exception"] = {
            "type": (
                record["exception"].type.__name__ if record["exception"].type else None
            ),
            "value": (
                str(record["exception"].value) if record["exception"].value else None
            ),
            "traceback": traceback_text,
        }
    else:
        log_record["exception"] = None

    # Add process info
    log_record["process"] = {
        "id": record["process"].id,
        "name": record["process"].name,
    }

    # Add thread info
    log_record["thread"] = {
        "id": record["thread"].id,
        "name": record["thread"].name,
    }

    return log_record


def custom_json_sink(message):
    """
    Custom sink that wraps sys.stderr and formats logs as simplified JSON.
    """
    record = message.record
    log_record = build_simplified_json_record(record)
    sys.stderr.write(json.dumps(log_record) + "\n")


def otel_sink(message, otel_handler: logging.Handler):
    """
    Bridge loguru records to OpenTelemetry logging handler.

    This function converts loguru records to standard logging.LogRecord format
    and emits them to the OpenTelemetry handler for OTLP export.

    Args:
        message: Loguru message object
        otel_handler: OpenTelemetry LoggingHandler instance
    """
    record = message.record

    # Convert loguru record to standard logging.LogRecord
    log_record = logging.LogRecord(
        name=record["name"],
        level=record["level"].no,
        pathname=record["file"].path,
        lineno=record["line"],
        msg=record["message"],
        args=(),
        exc_info=record["exception"],
    )

    # Add context (request_id, job_id) as extra attributes
    if "request_id" in record["extra"]:
        log_record.request_id = record["extra"]["request_id"]
    if "job_id" in record["extra"]:
        log_record.job_id = record["extra"]["job_id"]

    # Emit to OpenTelemetry handler
    otel_handler.emit(log_record)


def configure_logging(otel_handler: Optional[logging.Handler] = None):
    """
    Configure logging for the application using loguru.

    Args:
        otel_handler: Optional OpenTelemetry LoggingHandler for OTLP log export

    This function:
    1. Removes default loguru handler
    2. Adds custom JSON sink for simplified JSON logging (console)
    3. Adds OpenTelemetry sink if handler provided (OTLP export)
    4. Configures context filter to automatically inject request_id and job_id from contextvars
    5. Intercepts all standard logging calls to redirect to loguru
    6. Configures log level from settings
    """
    # Remove default handler
    logger.remove()

    # Determine log level (required - will fail if not set in environment)
    log_level = settings.LOG_LEVEL

    # Add console handler with custom JSON sink
    logger.add(
        custom_json_sink,  # Use custom JSON sink
        level=log_level,
        backtrace=True,
        diagnose=True,
        filter=context_filter,  # This filter injects request_id and job_id automatically
    )

    # Add OpenTelemetry sink if handler provided
    if otel_handler:
        logger.add(
            lambda msg: otel_sink(msg, otel_handler),
            level=log_level,
            filter=context_filter,  # Also add filter to OTel handler
            format="{message}",  # Simple format since OTel handles structured logging
        )
        logger.info("OpenTelemetry logging sink configured")

    # Intercept standard logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Set logging level for commonly verbose libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    logger.info("Logging configured successfully with loguru")


def set_request_id(request_id: str):
    """
    Set the request_id for the current context.

    This should be called at the beginning of each request (in middleware).
    All subsequent logs in this request context will automatically include this request_id.

    Args:
        request_id: The request ID to set
    """
    request_id_var.set(request_id)


def set_job_id(job_id: str):
    """
    Set the job_id for the current context.

    This should be called at the beginning of each job (in worker).
    All subsequent logs in this job context will automatically include this job_id.

    Args:
        job_id: The job ID to set
    """
    job_id_var.set(job_id)


def clear_request_id():
    """
    Clear the request_id from the current context.

    This is typically called at the end of request processing.
    """
    request_id_var.set("-")


def clear_job_id():
    """
    Clear the job_id from the current context.

    This is typically called at the end of job processing.
    """
    job_id_var.set("-")


def get_request_id() -> str:
    """Get the current request_id from context."""
    return request_id_var.get()


def get_job_id() -> str:
    """Get the current job_id from context."""
    return job_id_var.get()
