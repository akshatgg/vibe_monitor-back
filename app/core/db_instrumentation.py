"""
Database instrumentation using SQLAlchemy event listeners.
Tracks transaction metrics, connection pool usage, and active connections.
"""

import logging
from contextvars import ContextVar
from typing import Optional

from opentelemetry.metrics import CallbackOptions, Observation
from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# track transaction start time per session
_transaction_start_time: ContextVar[Optional[float]] = ContextVar(
    "transaction_start_time", default=None
)
_engine: Optional[Engine] = None


def get_pool_size_callback(options: CallbackOptions):
    """
    Callback for Observable Gauge - returns current pool statistics.

    This function is called automatically by OpenTelemetry when collecting metrics
    """
    try:
        if _engine is None:
            logger.warning("Engine not initialized for pool size callback")
            return []

        pool = _engine.sync_engine.pool

        # Get pool statistics
        pool_size = pool.size()
        checked_out = pool.checkedout()
        overflow = pool.overflow()

        # Total connections = base + overflow
        total_connections = pool_size + overflow

        return [
            Observation(pool_size, {"metric": "base_pool_size"}),
            Observation(overflow, {"metric": "overflow_connections"}),
            Observation(checked_out, {"metric": "checked_out_connections"}),
            Observation(total_connections, {"metric": "total_connections"}),
        ]
    except Exception as e:
        logger.error(f"Error in pool size callback: {e}", exc_info=True)
        return []


def setup_database_instrumentation(engine: Engine):
    """
    Must be called AFTER otel_metrics.init_meter()

    Note: AsyncSession does not support session-level events like after_begin,
    before_commit, etc. We only instrument connection pool events which work
    for both sync and async engines.
    """
    from app.core.otel_metrics import DB_METRICS

    global _engine
    _engine = engine

    logger.info("Setting up database instrumentation with SQLAlchemy event listeners")

    # ==================== CONNECTION POOL EVENTS ====================
    # Note: Session-level events (after_begin, before_commit, etc.) are NOT available
    # for AsyncSession. We only track connection pool metrics which work with async.

    @event.listens_for(engine.sync_engine.pool, "checkout")
    def receive_checkout(dbapi_conn, connection_record, connection_proxy):
        """
        Track when a connection is checked out from the pool.
        """
        try:
            # Increment active connections when connection leaves pool
            DB_METRICS["db_connections_active"].add(1)
            logger.debug(f"Connection {id(dbapi_conn)} checked out from pool")
        except Exception as e:
            logger.error(f"Error in checkout event: {e}", exc_info=True)

    @event.listens_for(engine.sync_engine.pool, "checkin")
    def receive_checkin(dbapi_conn, connection_record):
        """
        Track when a connection is returned to the pool.
        """
        try:
            # Decrement active connections when connection returns to pool
            DB_METRICS["db_connections_active"].add(-1)
            logger.debug(f"Connection {id(dbapi_conn)} returned to pool")
        except Exception as e:
            logger.error(f"Error in checkin event: {e}", exc_info=True)

    logger.info("Database instrumentation event listeners registered successfully")
