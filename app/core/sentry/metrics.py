"""
Sentry metrics dual-write layer.

Wraps existing OTEL metric dicts so every .add() / .record() call
automatically emits to Sentry as well. OTEL code stays untouched —
this module patches the dicts externally at startup.

Call wrap_otel_metrics() once after init_meter() in main.py.
"""

import logging
from typing import Any, Dict

import sentry_sdk

from app.core.config import settings

logger = logging.getLogger(__name__)

# Maps OTEL metric dict key → Sentry metric name
_SENTRY_NAME_MAP: Dict[str, str] = {
    "jobs_created_total": "vm_api.jobs.created.total",
    "jobs_succeeded_total": "vm_api.jobs.succeeded.total",
    "jobs_failed_total": "vm_api.jobs.failed.total",
    "rca_agent_invocations_total": "vm_api.rca.agent.invocations.total",
    "rca_agent_duration_seconds": "vm_api.rca.agent.duration",
    "rca_agent_retries_total": "vm_api.rca.agent.retries.total",
    "rca_llm_provider_usage_total": "vm_api.rca.llm.provider.usage.total",
    "rca_context_size_bytes": "vm_api.rca.context.size.bytes",
    "rca_estimated_input_tokens": "vm_api.rca.estimated.input.tokens",
    "rca_tool_executions_total": "vm_api.rca.tool.executions.total",
    "rca_tool_execution_duration_seconds": "vm_api.rca.tool.execution.duration",
    "rca_tool_execution_errors_total": "vm_api.rca.tool.execution.errors.total",
    "auth_failures_total": "vm_api.auth.failures.total",
    "jwt_tokens_expired_total": "vm_api.auth.jwt.tokens.expired.total",
    "llm_guard_blocked_messages_total": "vm_api.security.llm_guard.blocked.total",
    "security_events_created_total": "vm_api.security.events.created.total",
    "rate_limit_exceeded_total": "vm_api.rate_limit.exceeded.total",
    "db_connections_active": "vm_api.db.connections.active",
    "db_transactions_total": "vm_api.db.transactions.total",
    "db_transaction_duration_seconds": "vm_api.db.transaction.duration",
    "db_rollbacks_total": "vm_api.db.rollbacks.total",
    "sqs_messages_sent": "vm_api.sqs.messages.sent",
    "sqs_messages_received": "vm_api.sqs.messages.received",
    "sqs_message_parse_errors_total": "vm_api.sqs.message.parse_errors.total",
    "slack_messages_sent": "vm_api.slack.messages.sent",
    "github_api_calls_total": "vm_api.github.api.calls.total",
    "github_api_duration_seconds": "vm_api.github.api.duration",
    "github_api_rate_limit_remaining": "vm_api.github.api.rate_limit.remaining",
    "github_token_refreshes_total": "vm_api.github.token.refreshes.total",
    "stripe_api_calls_total": "vm_api.stripe.api.calls.total",
    "stripe_payment_failures_total": "vm_api.stripe.payment.failures.total",
    "http_requests_total": "vm_api.http.requests.total",
    "http_request_duration_seconds": "vm_api.http.request.duration",
    "http_response_size_bytes": "vm_api.http.response.size.bytes",
    "active_workspaces": "vm_api.workspaces.active",
    "workspace_created_total": "vm_api.workspaces.created.total",
}


def _sentry_enabled() -> bool:
    return bool(settings.SENTRY_DSN and settings.SENTRY_METRICS_ENABLED)


class SentryDualWriteMetric:
    """Wraps an OTEL metric (or NoOpMetric) to also emit to Sentry.

    Call sites keep using .add() and .record() — this class forwards to both
    the underlying OTEL instrument and sentry_sdk.metrics.
    """

    def __init__(self, otel_metric: Any, sentry_name: str):
        self._otel = otel_metric
        self._sentry_name = sentry_name

    def add(self, amount: int | float, attributes: dict[str, Any] | None = None):
        self._otel.add(amount, attributes)
        if _sentry_enabled():
            sentry_sdk.metrics.count(self._sentry_name, amount, attributes=attributes)

    def record(self, amount: int | float, attributes: dict[str, Any] | None = None):
        self._otel.record(amount, attributes)
        if _sentry_enabled():
            sentry_sdk.metrics.distribution(
                self._sentry_name, amount, attributes=attributes
            )


def wrap_otel_metrics() -> None:
    """Patch all OTEL metric dicts to dual-write to Sentry.

    Call once after init_meter() in main.py. Replaces each metric instrument
    in the OTEL dicts with a SentryDualWriteMetric wrapper.
    Skips observable gauges (callback-based, not wrappable).
    """
    if not settings.SENTRY_DSN:
        logger.info("Sentry DSN not set — skipping metrics wrapping")
        return

    from app.core.otel_metrics import (
        AGENT_METRICS,
        AUTH_METRICS,
        DB_METRICS,
        GITHUB_METRICS,
        HTTP_METRICS,
        JOB_METRICS,
        LLM_METRICS,
        SECURITY_METRICS,
        SLACK_METRICS,
        SQS_METRICS,
        STRIPE_METRICS,
        TOOL_METRICS,
        WORKSPACE_METRICS,
    )

    all_dicts = [
        AGENT_METRICS,
        LLM_METRICS,
        TOOL_METRICS,
        AUTH_METRICS,
        SECURITY_METRICS,
        JOB_METRICS,
        DB_METRICS,
        SQS_METRICS,
        SLACK_METRICS,
        GITHUB_METRICS,
        STRIPE_METRICS,
        HTTP_METRICS,
        WORKSPACE_METRICS,
    ]

    wrapped_count = 0
    for metrics_dict in all_dicts:
        for key in list(metrics_dict.keys()):
            if key not in _SENTRY_NAME_MAP:
                continue
            # Skip if already wrapped or if it's an observable gauge (no add/record)
            metric = metrics_dict[key]
            if isinstance(metric, SentryDualWriteMetric):
                continue
            if not (hasattr(metric, "add") or hasattr(metric, "record")):
                continue
            metrics_dict[key] = SentryDualWriteMetric(
                metric, _SENTRY_NAME_MAP[key]
            )
            wrapped_count += 1

    logger.info("Sentry metrics wrapping complete: %d metrics wrapped", wrapped_count)
