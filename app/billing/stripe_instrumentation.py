"""
Stripe metrics instrumentation helpers.
"""

import asyncio
import logging
import time
from functools import wraps
from typing import Any, Callable, Optional

from opentelemetry.metrics import CallbackOptions, Observation

logger = logging.getLogger(__name__)

# Cached subscription count
_cached_active_subscriptions: Optional[int] = None


def get_active_subscriptions_callback(options: CallbackOptions):
    """
    Observable Gauge callback for active Stripe subscriptions.
    Called automatically by OpenTelemetry every collection interval.
    """
    try:
        if _cached_active_subscriptions is not None:
            return [Observation(_cached_active_subscriptions, {})]
        else:
            return []
    except Exception as e:
        logger.error(f"Error in active subscriptions callback: {e}", exc_info=True)
        return []


async def update_subscription_metrics_cache():
    """
    Updates the cached subscription count for metrics collection.
    Should be called periodically by a background task.
    """
    global _cached_active_subscriptions

    try:
        from app.core.database import AsyncSessionLocal
        from app.billing.services.subscription_service import subscription_service

        async with AsyncSessionLocal() as db:
            count = await subscription_service.count_active_subscriptions(db)
            _cached_active_subscriptions = count
            logger.debug(f"Updated subscription metrics cache: {count} active subscriptions")
    except Exception as e:
        logger.error(f"Error updating subscription metrics cache: {e}", exc_info=True)


def stripe_api_metric(operation_name: str):
    """
    Decorator to instrument Stripe API calls with metrics.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:

            from app.core.otel_metrics import STRIPE_METRICS

            start_time = time.time()
            success = False

            try:
                result = await func(*args, **kwargs)
                success = True
                return result
            except Exception as e:
                logger.error(f"Stripe API error in {operation_name}: {e}")
                raise
            finally:
                duration = time.time() - start_time

                STRIPE_METRICS["stripe_api_calls_total"].add(1, {
                    "operation": operation_name,
                    "status": "success" if success else "error"
                })

                logger.debug(f"Stripe {operation_name} took {duration:.3f}s")

        return wrapper
    return decorator
