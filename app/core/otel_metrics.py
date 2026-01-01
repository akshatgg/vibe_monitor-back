"""
OpenTelemetry metrics for VM-API
Custom business metrics for RCA, database, SQS, Slack, GitHub, and workspaces
"""

import logging
from typing import Any, Dict, Optional

from opentelemetry.metrics import Meter

logger = logging.getLogger(__name__)

# Global meter instance (initialized in main.py)
_meter: Optional[Meter] = None

# Metrics dictionaries (initialized after meter is set)
RCA_METRICS: Dict[str, Any] = {}
DB_METRICS: Dict[str, Any] = {}
SQS_METRICS: Dict[str, Any] = {}
SLACK_METRICS: Dict[str, Any] = {}
GITHUB_METRICS: Dict[str, Any] = {}
WORKSPACE_METRICS: Dict[str, Any] = {}
JOB_METRICS: Dict[str, Any] = {}


def init_meter(meter: Meter):
    """
    Initialize OpenTelemetry meter and create all metric instruments

    Args:
        meter: OpenTelemetry Meter instance from MeterProvider

    Note:
        This should be called once during application startup
    """
    global \
        _meter, \
        RCA_METRICS, \
        DB_METRICS, \
        SQS_METRICS, \
        SLACK_METRICS, \
        GITHUB_METRICS, \
        WORKSPACE_METRICS, \
        JOB_METRICS

    _meter = meter

    # ==================== RCA JOB METRICS ====================
    RCA_METRICS = {
        "rca_jobs_total": meter.create_counter(
            name="vm_api.rca.jobs.total",
            description="Total number of RCA jobs processed",
            unit="1",
        ),
        "rca_job_duration": meter.create_histogram(
            name="vm_api.rca.job.duration",
            description="RCA job processing duration",
            unit="s",
        ),
        "rca_jobs_active": meter.create_up_down_counter(
            name="vm_api.rca.jobs.active",
            description="Number of currently active RCA jobs",
            unit="1",
        ),
    }

    # ==================== JOB METRICS (SLACK) ====================
    JOB_METRICS.clear()
    JOB_METRICS.update({
        "jobs_created_total": meter.create_counter(
            name="vm_api.jobs.created.total",
            description="Total number of jobs created",
            unit="1",
        ),
        "jobs_succeeded_total": meter.create_counter(
            name="vm_api.jobs.succeeded.total",
            description="Total number of successful jobs",
            unit="1",
        ),
        "jobs_failed_total": meter.create_counter(
            name="vm_api.jobs.failed.total",
            description="Total number of failed jobs",
            unit="1",
        ),
    })

    # ==================== DATABASE METRICS ====================
    DB_METRICS = {
        "db_connections_active": meter.create_up_down_counter(
            name="vm_api.db.connections.active",
            description="Active database connections",
            unit="1",
        ),
        "db_query_duration": meter.create_histogram(
            name="vm_api.db.query.duration",
            description="Database query duration",
            unit="s",
        ),
    }

    # ==================== SQS METRICS ====================
    SQS_METRICS = {
        "sqs_messages_sent": meter.create_counter(
            name="vm_api.sqs.messages.sent",
            description="Total SQS messages sent",
            unit="1",
        ),
        "sqs_messages_received": meter.create_counter(
            name="vm_api.sqs.messages.received",
            description="Total SQS messages received",
            unit="1",
        ),
    }

    # ==================== SLACK METRICS ====================
    SLACK_METRICS = {
        "slack_messages_sent": meter.create_counter(
            name="vm_api.slack.messages.sent",
            description="Total Slack messages sent",
            unit="1",
        ),
    }

    # ==================== GITHUB METRICS ====================
    GITHUB_METRICS = {
        "github_api_calls": meter.create_counter(
            name="vm_api.github.api.calls",
            description="Total GitHub API calls",
            unit="1",
        ),
    }

    # ==================== WORKSPACE METRICS ====================
    WORKSPACE_METRICS = {
        "active_workspaces": meter.create_up_down_counter(
            name="vm_api.workspaces.active",
            description="Number of active workspaces",
            unit="1",
        ),
    }

    logger.info("OpenTelemetry metrics instruments initialized")


# ==================== USAGE EXAMPLES ====================
#
# Counter (monotonically increasing):
#   RCA_METRICS["rca_jobs_total"].add(1, {"status": "completed"})
#   RCA_METRICS["rca_jobs_total"].add(1, {"status": "failed"})
#
# Histogram (records distribution of values):
#   RCA_METRICS["rca_job_duration"].record(5.2, {"status": "completed"})
#   DB_METRICS["db_query_duration"].record(0.15, {"query_type": "select"})
#
# UpDownCounter (can increase or decrease):
#   RCA_METRICS["rca_jobs_active"].add(1)  # Job started
#   RCA_METRICS["rca_jobs_active"].add(-1)  # Job finished
#
# Attributes (labels in Prometheus):
#   Passed as dict in second argument: {"status": "completed", "workspace_id": "123"}
#
# ==================== MIGRATION GUIDE ====================
#
# OLD (Prometheus):
#   from app.core.metrics import rca_jobs_total, rca_job_duration_seconds
#   rca_jobs_total.labels(status="completed").inc()
#   rca_job_duration_seconds.labels(status="completed").observe(5.2)
#
# NEW (OpenTelemetry):
#   from app.core.otel_metrics import RCA_METRICS
#   RCA_METRICS["rca_jobs_total"].add(1, {"status": "completed"})
#   RCA_METRICS["rca_job_duration"].record(5.2, {"status": "completed"})
#
