"""
Langfuse integration for RCA agent observability.

Provides callback handlers for tracing LangChain agent executions
to Langfuse for debugging and analytics.
"""

import logging
from typing import Any, Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Langfuse callback handler (initialized lazily)
_langfuse_handler = None
_initialization_attempted = False


def get_langfuse_callback(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[list] = None,
):
    """
    Get a Langfuse callback handler for LangChain agent tracing.

    Args:
        session_id: Optional session ID for grouping traces (e.g., Slack thread_ts)
        user_id: Optional user ID for the trace
        metadata: Optional metadata dict to attach to the trace
        tags: Optional list of tags for filtering traces

    Returns:
        CallbackHandler if Langfuse is enabled and configured, None otherwise
    """
    global _langfuse_handler, _initialization_attempted

    # Check if Langfuse is enabled
    if not settings.LANGFUSE_ENABLED:
        return None

    # Check if keys are configured
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        if not _initialization_attempted:
            logger.warning(
                "Langfuse enabled but LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set. "
                "Langfuse tracing disabled."
            )
            _initialization_attempted = True
        return None

    try:
        from langfuse.callback import CallbackHandler

        # Create callback handler with trace context
        handler = CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
            session_id=session_id,
            user_id=user_id,
            metadata=metadata or {},
            tags=tags or [],
        )

        # Re-apply log level suppression — the Langfuse client constructor
        # resets the "langfuse" logger to WARNING, overriding our configure_logging() setting.
        logging.getLogger("langfuse").setLevel(
            getattr(logging, settings.LANGFUSE_LOG_LEVEL.upper(), logging.ERROR)
        )

        logger.debug(
            f"Created Langfuse callback handler (session={session_id}, user={user_id})"
        )
        return handler

    except ImportError:
        if not _initialization_attempted:
            logger.warning("langfuse package not installed. Langfuse tracing disabled.")
            _initialization_attempted = True
        return None
    except Exception as e:
        logger.error(f"Failed to create Langfuse callback handler: {e}")
        return None


def flush_langfuse():
    """
    Flush any pending Langfuse events.

    Call this at application shutdown to ensure all traces are sent.
    """
    try:
        from langfuse import Langfuse

        langfuse = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        langfuse.flush()
        logger.info("Langfuse events flushed successfully")
    except Exception as e:
        logger.error(f"Failed to flush Langfuse events: {e}")
