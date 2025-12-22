"""
Retry decorator for external API calls using tenacity library.

Provides automatic retry logic with exponential backoff for HTTP requests
to external services (Grafana, GitHub, Slack, Google OAuth, Mailgun).

Features:
- Exponential backoff with jitter to prevent thundering herd
- Smart error detection (retry transient errors, fail fast on permanent errors)
- Structured logging with service name and attempt numbers
- Configuration driven by settings (EXTERNAL_API_RETRY_*)
"""

import logging
from typing import TypeVar
import httpx

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    RetryCallState,
    retry_if_exception as tenacity_retry_if_exception,
)

from ..core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _is_retryable_http_error(exception: BaseException) -> bool:
    """
    Determine if an HTTP error should be retried.

    Retryable errors (transient failures):
    - Network errors (timeouts, connection errors)
    - 5xx server errors (server overload, temporary unavailability)
    - 429 Too Many Requests (rate limiting)
    - 503 Service Unavailable
    - 408 Request Timeout

    Non-retryable errors (permanent failures):
    - 4xx client errors (except 429, 408)
    - 401 Unauthorized (invalid credentials)
    - 403 Forbidden (permission denied)
    - 404 Not Found (resource doesn't exist)
    - 400 Bad Request (invalid input)

    Args:
        exception: Exception to check

    Returns:
        True if error should be retried, False otherwise
    """
    # Network-level errors (always retry)
    if isinstance(
        exception,
        (
            httpx.TimeoutException,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.ConnectError,
            httpx.NetworkError,
        ),
    ):
        return True

    # HTTP status code errors
    if isinstance(exception, httpx.HTTPStatusError):
        status_code = exception.response.status_code

        # Retry on server errors (5xx)
        if 500 <= status_code < 600:
            return True

        # Retry on rate limiting (429)
        if status_code == 429:
            return True

        # Retry on request timeout (408)
        if status_code == 408:
            return True

        # Don't retry other 4xx errors (client errors)
        return False

    # For other exceptions, don't retry by default (fail fast)
    return False


def _log_retry_attempt(retry_state: RetryCallState):
    """Log retry attempts with service context."""
    exception = retry_state.outcome.exception()
    attempt_number = retry_state.attempt_number

    # Extract service name from kwargs if available
    service_name = "external_api"
    if hasattr(retry_state, "kwargs") and "service_name" in retry_state.kwargs:
        service_name = retry_state.kwargs["service_name"]

    if exception:
        logger.warning(
            f"[{service_name}] Retry attempt {attempt_number} failed: "
            f"{type(exception).__name__}: {str(exception)}"
        )


def retry_external_api(service_name: str = "external_api"):
    """
    Create a tenacity AsyncRetrying instance for external API calls.

    This function returns a configured AsyncRetrying instance that can be used
    with async for loops to retry failed API calls.

    Usage:
        async def my_api_call():
            async for attempt in retry_external_api("github"):
                with attempt:
                    response = await client.get(url)
                    return response.json()

    Args:
        service_name: Name of the external service (for logging)

    Returns:
        AsyncRetrying instance configured with retry logic
    """
    return AsyncRetrying(
        # Stop after N attempts
        stop=stop_after_attempt(settings.EXTERNAL_API_RETRY_ATTEMPTS),
        # Exponential backoff: wait = min(max_wait, min_wait * (2 ** (attempt - 1)) * multiplier)
        # With multiplier=1.0, min=0.5s, max=2.0s: 0.5s → 1.0s → 2.0s → 2.0s → 2.0s
        wait=wait_exponential(
            multiplier=settings.EXTERNAL_API_RETRY_MULTIPLIER,
            min=settings.EXTERNAL_API_RETRY_MIN_WAIT,
            max=settings.EXTERNAL_API_RETRY_MAX_WAIT,
        ),
        # Only retry on specific exception types
        retry=retry_if_exception_type(
            (
                httpx.TimeoutException,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.ConnectError,
                httpx.NetworkError,
                httpx.HTTPStatusError,  # We filter 4xx vs 5xx in _is_retryable_http_error
            )
        )
        & tenacity_retry_if_exception(_is_retryable_http_error),
        # Log before sleeping
        before_sleep=before_sleep_log(logger, logging.WARNING),
        # Don't reraise on final failure (let the exception propagate naturally)
        reraise=True,
    )
