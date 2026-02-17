"""
Centralized Sentry configuration and context helpers.

Provides initialization and scope-setting utilities so every Sentry event
(errors, logs, metrics) carries request_id, job_id, workspace_id, etc.

OTEL + New Relic are NOT affected — this runs alongside them.
"""

import logging

import sentry_sdk

from app.core.config import settings

logger = logging.getLogger(__name__)


def init_sentry() -> None:
    """Initialize Sentry SDK with full configuration.

    Called once at app startup (main.py). No-op if SENTRY_DSN is not set.
    """
    if not settings.SENTRY_DSN:
        logger.info("Sentry DSN not configured — skipping initialization")
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=(
            1.0 if settings.is_local else settings.SENTRY_TRACES_SAMPLE_RATE
        ),
        environment=settings.ENVIRONMENT,
        send_default_pii=True,
        enable_logs=True,
        enable_tracing=True,
    )
    logger.info("Sentry initialized (environment=%s)", settings.ENVIRONMENT)


def set_sentry_context(
    *,
    request_id: str | None = None,
    job_id: str | None = None,
    workspace_id: str | None = None,
    service_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Set Sentry scope tags for the current execution context.

    Call this from middleware (request_id) and workers (job_id, workspace_id, etc.)
    so every Sentry event in that context is tagged for filtering/search.
    """
    if not settings.SENTRY_DSN or not settings.SENTRY_ENABLED:
        return

    if request_id:
        sentry_sdk.set_tag("request_id", request_id)
    if job_id:
        sentry_sdk.set_tag("job_id", job_id)
    if workspace_id:
        sentry_sdk.set_tag("workspace_id", workspace_id)
    if service_id:
        sentry_sdk.set_tag("service_id", service_id)
    if user_id:
        sentry_sdk.set_user({"id": user_id})


def clear_sentry_context() -> None:
    """Clear Sentry scope tags after request/job completes."""
    if not settings.SENTRY_DSN or not settings.SENTRY_ENABLED:
        return

    sentry_sdk.set_user(None)
    sentry_sdk.set_tag("request_id", "")
    sentry_sdk.set_tag("job_id", "")
    sentry_sdk.set_tag("workspace_id", "")
    sentry_sdk.set_tag("service_id", "")
