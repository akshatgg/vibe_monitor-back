"""
Centralized logging configuration with request_id and job_id context support using stdlib logging.

This module configures stdlib logging with JSON formatting and provides
automatic context propagation using contextvars. Also supports OpenTelemetry log export.

Includes PII masking filter to automatically sanitize sensitive data in logs.

Uses ONLY stdlib - no external logging dependencies (except for PII masking).
"""

import json
import logging
import sys
import threading
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Dict, Optional

from app.core.config import settings
from app.utils.data_masker import mask_log_message

# Context variables for request_id and job_id
# These are thread-safe and async-safe context variables
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
job_id_var: ContextVar[str] = ContextVar("job_id", default="-")


class PIIMaskingFilter(logging.Filter):
    """
    Safety net filter that masks secrets in log messages (NOT code/data).

    This filter ONLY masks data in log output - it does NOT mask:
    - Code or application data
    - API request/response payloads
    - Database records
    - In-memory variables

    Uses fast regex to catch accidental secret leaks in logs:
    - AWS keys (AKIA...)
    - GitHub tokens (ghp_...)
    - Slack tokens (xox...)
    - JWT tokens
    - Database connection strings

    Note: Primary defense is not logging PII/secrets in the first place.
    This is just a safety net for accidents.
    For customer data (queries, logs, code), use PIIMapper in data_masker.py.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Mask PII in the log message."""
        try:
            # Mask the main message
            if record.msg and isinstance(record.msg, str):
                record.msg = mask_log_message(record.msg)

            # Also mask any string arguments
            if record.args:
                masked_args = []
                for arg in record.args:
                    if isinstance(arg, str):
                        masked_args.append(mask_log_message(arg))
                    else:
                        masked_args.append(arg)
                record.args = tuple(masked_args)

        except Exception:
            # If masking fails, let the log through unmasked
            # This ensures logging doesn't break the application
            pass

        return True


class ContextFilter(logging.Filter):
    """
    Filter that adds request_id and job_id from contextvars to log records.

    This allows all logs within a request/job to automatically include the context
    without needing to manually bind the logger everywhere.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add context variables to the log record."""
        # Add request_id if set
        request_id = request_id_var.get()
        if request_id and request_id != "-":
            record.request_id = request_id

        # Add job_id if set
        job_id = job_id_var.get()
        if job_id and job_id != "-":
            record.job_id = job_id

        # Add process and thread info
        record.process_id = threading.current_thread().ident
        record.process_name = "MainProcess"  # For compatibility
        record.thread_name = threading.current_thread().name

        return True


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter using only stdlib - no external dependencies.

    Outputs simplified, clean JSON logs with essential fields:
    - timestamp
    - level
    - message
    - request_id (if present)
    - job_id (if present)
    - exception (if present)
    - process info
    - thread info
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        # Build log record dictionary (explicitly typed to satisfy mypy)
        log_record: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        # Add request_id if present
        if hasattr(record, "request_id"):
            log_record["request_id"] = record.request_id

        # Add job_id if present
        if hasattr(record, "job_id"):
            log_record["job_id"] = record.job_id

        # Add exception if present
        if record.exc_info:
            log_record["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "value": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info),
            }
        else:
            log_record["exception"] = None

        # Add process info
        log_record["process"] = {
            "id": getattr(record, "process_id", 0),
            "name": getattr(record, "process_name", "MainProcess"),
        }

        # Add thread info
        log_record["thread"] = {
            "id": getattr(record, "process_id", 0),  # Using process_id for thread id
            "name": getattr(record, "thread_name", "MainThread"),
        }

        # Return JSON string
        return json.dumps(log_record)


def configure_logging(otel_handler: Optional[logging.Handler] = None):
    """
    Configure logging for the application using stdlib logging.

    Args:
        otel_handler: Optional OpenTelemetry LoggingHandler for OTLP log export

    This function:
    1. Configures root logger with JSON formatter
    2. Adds context filter to automatically inject request_id and job_id from contextvars
    3. Adds OpenTelemetry handler if provided (OTLP export)
    4. Configures log level from settings
    5. Suppresses overly verbose library logs
    """
    # Get root logger
    root_logger = logging.getLogger()

    # Remove all existing handlers
    root_logger.handlers.clear()

    # Determine log level (required - will fail if not set in environment)
    log_level = getattr(logging, settings.LOG_LEVEL.upper())

    # Create filters
    context_filter = ContextFilter()
    pii_masking_filter = PIIMaskingFilter()

    # Create console handler with JSON formatter
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)

    # Use custom JSON formatter (stdlib only!)
    json_formatter = JSONFormatter()
    console_handler.setFormatter(json_formatter)
    # Apply PII masking filter first, then context filter
    console_handler.addFilter(pii_masking_filter)
    console_handler.addFilter(context_filter)

    # Add console handler to root logger
    root_logger.addHandler(console_handler)
    root_logger.setLevel(log_level)

    # Add OpenTelemetry handler if provided
    if otel_handler:
        otel_handler.setLevel(log_level)
        otel_handler.addFilter(pii_masking_filter)
        otel_handler.addFilter(context_filter)
        root_logger.addHandler(otel_handler)
        logging.info("OpenTelemetry logging handler configured")

    # Set logging level for commonly verbose libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # CRITICAL: Suppress OpenTelemetry attribute warnings that were causing noise
    logging.getLogger("opentelemetry.attributes").setLevel(logging.ERROR)
    logging.getLogger("opentelemetry.sdk.trace").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry.sdk.metrics").setLevel(logging.WARNING)

    # Suppress verbose Presidio initialization logs and warnings
    # Presidio emits very verbose INFO/WARNING logs during initialization:
    # - NLP model loading messages (spaCy, transformers)
    # - Recognizer registry initialization
    # - Unsupported language warnings (we only use English)
    # These logs clutter our application logs without providing value.
    # We only care about actual errors, so set to ERROR level.
    logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)
    logging.getLogger("presidio_analyzer").setLevel(logging.ERROR)
    logging.getLogger("presidio_anonymizer").setLevel(logging.ERROR)
    logging.getLogger("presidio_analyzer.recognizer_registry").setLevel(logging.ERROR)
    logging.getLogger("presidio_analyzer.nlp_engine").setLevel(logging.ERROR)

    logging.info("Logging configured successfully with stdlib logging")


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
