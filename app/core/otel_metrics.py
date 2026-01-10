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
AGENT_METRICS: Dict[str, Any] = {}
LLM_METRICS: Dict[str, Any] = {}
TOOL_METRICS: Dict[str, Any] = {}
AUTH_METRICS: Dict[str, Any] = {}
SECURITY_METRICS: Dict[str, Any] = {}
DB_METRICS: Dict[str, Any] = {}
SQS_METRICS: Dict[str, Any] = {}
SLACK_METRICS: Dict[str, Any] = {}
GITHUB_METRICS: Dict[str, Any] = {}
STRIPE_METRICS: Dict[str, Any] = {}
HTTP_METRICS: Dict[str, Any] = {}
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

    from app.billing.stripe_instrumentation import get_active_subscriptions_callback
    from app.core.db_instrumentation import get_pool_size_callback

    global _meter
    _meter = meter
    # Note: We use .clear() + .update() instead of reassignment to preserve
    # dict identity for modules that imported these at load time

    # ==================== RCA AGENT METRICS ====================
    # Use clear() + update() to preserve dict identity for modules that imported at load time
    AGENT_METRICS.clear()
    AGENT_METRICS.update(
        {
            "rca_agent_invocations_total": meter.create_counter(
                name="vm_api.rca.agent.invocations.total",
                description="Total number of RCA agent invocations",
                unit="1",
            ),
            "rca_agent_duration_seconds": meter.create_histogram(
                name="vm_api.rca.agent.duration",
                description="RCA agent execution duration",
                unit="s",
            ),
            "rca_agent_retries_total": meter.create_counter(
                name="vm_api.rca.agent.retries.total",
                description="Total number of RCA agent retry attempts",
                unit="1",
            ),
        }
    )

    # ==================== RCA LLM PROVIDER METRICS ====================
    LLM_METRICS.clear()
    LLM_METRICS.update(
        {
            "rca_llm_provider_usage_total": meter.create_counter(
                name="vm_api.rca.llm.provider.usage.total",
                description="Total LLM provider invocations by type",
                unit="1",
            ),
            "rca_context_size_bytes": meter.create_histogram(
                name="vm_api.rca.context.size.bytes",
                description="Size of context sent to LLM in bytes",
                unit="By",
            ),
            "rca_estimated_input_tokens": meter.create_histogram(
                name="vm_api.rca.estimated.input.tokens",
                description="Estimated number of input tokens sent to LLM",
                unit="1",
            ),
        }
    )

    # ==================== RCA TOOL EXECUTION METRICS ====================
    TOOL_METRICS.clear()
    TOOL_METRICS.update(
        {
            "rca_tool_executions_total": meter.create_counter(
                name="vm_api.rca.tool.executions.total",
                description="Total number of tool executions",
                unit="1",
            ),
            "rca_tool_execution_duration_seconds": meter.create_histogram(
                name="vm_api.rca.tool.execution.duration",
                description="Tool execution duration",
                unit="s",
            ),
            "rca_tool_execution_errors_total": meter.create_counter(
                name="vm_api.rca.tool.execution.errors.total",
                description="Total number of tool execution errors",
                unit="1",
            ),
        }
    )

    # ==================== AUTHENTICATION METRICS ====================
    AUTH_METRICS.clear()
    AUTH_METRICS.update(
        {
            "auth_failures_total": meter.create_counter(
                name="vm_api.auth.failures.total",
                description="Total number of failed authentication attempts",
                unit="1",
            ),
            "jwt_tokens_expired_total": meter.create_counter(
                name="vm_api.auth.jwt.tokens.expired.total",
                description="Total number of expired JWT tokens detected",
                unit="1",
            ),
        }
    )

    # ==================== SECURITY METRICS ====================
    SECURITY_METRICS.clear()
    SECURITY_METRICS.update(
        {
            "llm_guard_blocked_messages_total": meter.create_counter(
                name="vm_api.security.llm_guard.blocked.total",
                description="Total number of messages blocked by LLM security guard",
                unit="1",
            ),
            "security_events_created_total": meter.create_counter(
                name="vm_api.security.events.created.total",
                description="Total number of security events created",
                unit="1",
            ),
            "rate_limit_exceeded_total": meter.create_counter(
                name="vm_api.rate_limit.exceeded.total",
                description="Total number of rate limit violations",
                unit="1",
            ),
        }
    )

    # ==================== JOB METRICS =========================
    JOB_METRICS.clear()
    JOB_METRICS.update(
        {
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
        }
    )

    # ==================== DATABASE METRICS ====================
    DB_METRICS.clear()
    DB_METRICS.update(
        {
            "db_connections_active": meter.create_up_down_counter(
                name="vm_api.db.connections.active",
                description="Active database connections",
                unit="1",
            ),
            "db_transactions_total": meter.create_counter(
                name="vm_api.db.transactions.total",
                description="Total number of database transactions (commits and rollbacks)",
                unit="1",
            ),
            "db_transaction_duration_seconds": meter.create_histogram(
                name="vm_api.db.transaction.duration",
                description="Database transaction duration from begin to commit/rollback",
                unit="s",
            ),
            "db_connection_pool_size": meter.create_observable_gauge(
                name="vm_api.db.connection_pool.size",
                callbacks=[get_pool_size_callback],
                description="Connection pool size metrics (base, overflow, checked out, total)",
                unit="1",
            ),
            "db_rollbacks_total": meter.create_counter(
                name="vm_api.db.rollbacks.total",
                description="Total number of database transaction rollbacks",
                unit="1",
            ),
        }
    )

    # ==================== SQS METRICS ====================
    SQS_METRICS.clear()
    SQS_METRICS.update(
        {
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
            "sqs_message_parse_errors_total": meter.create_counter(
                name="vm_api.sqs.message.parse_errors.total",
                description="Total SQS messages with JSON parse or schema errors",
                unit="1",
            ),
        }
    )

    # ==================== SLACK METRICS ====================
    SLACK_METRICS.clear()
    SLACK_METRICS.update(
        {
            "slack_messages_sent": meter.create_counter(
                name="vm_api.slack.messages.sent",
                description="Total Slack messages sent",
                unit="1",
            ),
        }
    )

    # ==================== GITHUB METRICS ====================
    GITHUB_METRICS.clear()
    GITHUB_METRICS.update(
        {
            "github_api_calls_total": meter.create_counter(
                name="vm_api.github.api.calls.total",
                description="Total GitHub API calls with detailed labels",
                unit="1",
            ),
            "github_api_duration_seconds": meter.create_histogram(
                name="vm_api.github.api.duration",
                description="GitHub API call duration for performance monitoring",
                unit="s",
            ),
            "github_api_rate_limit_remaining": meter.create_up_down_counter(
                name="vm_api.github.api.rate_limit.remaining",
                description="GitHub API rate limit remaining (from X-RateLimit-Remaining header)",
                unit="1",
            ),
            "github_token_refreshes_total": meter.create_counter(
                name="vm_api.github.token.refreshes.total",
                description="Total GitHub access token refreshes for auth health monitoring",
                unit="1",
            ),
        }
    )

    # ==================== STRIPE METRICS ====================
    STRIPE_METRICS.clear()
    STRIPE_METRICS.update(
        {
            "stripe_api_calls_total": meter.create_counter(
                name="vm_api.stripe.api.calls.total",
                description="Total Stripe API calls for rate limiting and quota tracking",
                unit="1",
            ),
            "stripe_payment_failures_total": meter.create_counter(
                name="vm_api.stripe.payment.failures.total",
                description="Total Stripe payment failures",
                unit="1",
            ),
            "stripe_subscriptions_active": meter.create_observable_gauge(
                name="vm_api.stripe.subscriptions.active",
                callbacks=[get_active_subscriptions_callback],
                description="Number of active Stripe subscriptions",
                unit="1",
            ),
        }
    )

    # ==================== HTTP REQUEST TELEMETRY ====================
    HTTP_METRICS.clear()
    HTTP_METRICS.update(
        {
            "http_requests_total": meter.create_counter(
                name="vm_api.http.requests.total",
                description="Total HTTP requests by endpoint, method, and status code",
                unit="1",
            ),
            "http_request_duration_seconds": meter.create_histogram(
                name="vm_api.http.request.duration",
                description="HTTP request duration for latency tracking",
                unit="s",
            ),
            "http_response_size_bytes": meter.create_histogram(
                name="vm_api.http.response.size.bytes",
                description="HTTP response body size for bandwidth monitoring",
                unit="By",
            ),
        }
    )

    # ==================== WORKSPACE METRICS ====================
    WORKSPACE_METRICS.clear()
    WORKSPACE_METRICS.update(
        {
            "active_workspaces": meter.create_up_down_counter(
                name="vm_api.workspaces.active",
                description="Number of active workspaces",
                unit="1",
            ),
            "workspace_created_total": meter.create_counter(
                name="vm_api.workspaces.created.total",
                description="Total number of workspaces created (growth tracking)",
                unit="1",
            ),
        }
    )

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
