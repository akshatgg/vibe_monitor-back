"""
Database instrumentation using SQLAlchemy event listeners.
Tracks transaction metrics, connection pool usage, and active connections.
"""

import logging
import time
from contextvars import ContextVar
from typing import Optional

from opentelemetry.metrics import CallbackOptions, Observation
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

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
    """
    from app.core.otel_metrics import DB_METRICS

    global _engine
    _engine = engine

    logger.info("Setting up database instrumentation with SQLAlchemy event listeners")

    # ==================== SESSION LIFECYCLE EVENTS ====================
    @event.listens_for(AsyncSession, "after_begin", propagate=True)
    def receive_after_begin(session, transaction, connection):
        """
        Track transaction start time for duration calculation.
        """
        try:
            # Only track top-level transactions
            if not transaction.nested:
                _transaction_start_time.set(time.time())

                logger.debug(f"Transaction started for session {id(session)}")
        except Exception as e:
            logger.error(f"Error in after_begin event: {e}", exc_info=True)

    @event.listens_for(AsyncSession, "before_commit", propagate=True)
    def receive_before_commit(session):
        """
        Record transaction duration and increment commit counter.
        """
        try:
            start_time = _transaction_start_time.get()
            if start_time:
                duration = time.time() - start_time

                DB_METRICS["db_transaction_duration_seconds"].record(
                    duration,
                    {"transaction_type": "commit"}
                )

                DB_METRICS["db_transactions_total"].add(
                    1,
                    {"transaction_type": "commit"}    
                )

                logger.debug(
                    f"Transaction committed in {duration:.3f}s for session {id(session)}"
                )
        except Exception as e:
            logger.error(f"Error in before_commit event: {e}", exc_info=True)

    @event.listens_for(AsyncSession, "after_commit", propagate=True)
    def receive_after_commit(session):
        """
        Clear transaction start time after commit completes.
        """
        try:
            _transaction_start_time.set(None)
        except Exception as e:
            logger.error(f"Error in after_commit event: {e}", exc_info=True)

    @event.listens_for(AsyncSession, "after_rollback", propagate=True)
    def receive_after_rollback(session):
        """
        Record rollback metrics and clear transaction start time.
        Fires after a transaction is rolled back.
        """
        try:
            start_time = _transaction_start_time.get()
            if start_time:
                duration = time.time() - start_time

                DB_METRICS["db_transaction_duration_seconds"].record(
                    duration,
                    {"transaction_type": "rollback"}
                )

                logger.debug(
                    f"Transaction rolled back after {duration:.3f}s for session {id(session)}"
                )

            DB_METRICS["db_transactions_total"].add(
                1,
                {"transaction_type": "rollback"}
            )
            DB_METRICS["db_rollbacks_total"].add(1)

            # Clear start time
            _transaction_start_time.set(None)

        except Exception as e:
            logger.error(f"Error in after_rollback event: {e}", exc_info=True)

    # ==================== CONNECTION POOL EVENTS ====================

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
