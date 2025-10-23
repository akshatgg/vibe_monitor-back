"""
Prometheus metrics configuration for VM-API
Push-based metrics using Pushgateway (similar to Promtail → Loki pattern)
"""
import logging
import os
import asyncio
from prometheus_client import Counter, Histogram, Gauge, Info, CollectorRegistry, push_to_gateway
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Use custom registry to avoid conflicts
REGISTRY = CollectorRegistry()

# Custom Prometheus metrics
# Note: HTTP request metrics (count, size, duration) are handled by prometheus-fastapi-instrumentator
# in setup_metrics() function below. Manual definitions here would cause conflicts.

# RCA Job metrics
rca_jobs_total = Counter(
    'vm_api_rca_jobs_total',
    'Total RCA jobs processed',
    ['status'],  # queued, running, completed, failed
    registry=REGISTRY
)

rca_job_duration_seconds = Histogram(
    'vm_api_rca_job_duration_seconds',
    'RCA job processing duration in seconds',
    ['status'],
    registry=REGISTRY
)

rca_jobs_active = Gauge(
    'vm_api_rca_jobs_active',
    'Number of currently active RCA jobs',
    registry=REGISTRY
)

# Database metrics
db_connections_active = Gauge(
    'vm_api_db_connections_active',
    'Active database connections',
    registry=REGISTRY
)

db_query_duration_seconds = Histogram(
    'vm_api_db_query_duration_seconds',
    'Database query duration in seconds',
    ['query_type'],
    registry=REGISTRY
)

# SQS metrics
sqs_messages_sent_total = Counter(
    'vm_api_sqs_messages_sent_total',
    'Total SQS messages sent',
    registry=REGISTRY
)

sqs_messages_received_total = Counter(
    'vm_api_sqs_messages_received_total',
    'Total SQS messages received',
    registry=REGISTRY
)

# Slack integration metrics
slack_messages_sent_total = Counter(
    'vm_api_slack_messages_sent_total',
    'Total Slack messages sent',
    ['team_id'],
    registry=REGISTRY
)

# GitHub integration metrics
github_api_calls_total = Counter(
    'vm_api_github_api_calls_total',
    'Total GitHub API calls',
    ['endpoint', 'status'],
    registry=REGISTRY
)

# Workspace metrics
active_workspaces = Gauge(
    'vm_api_active_workspaces',
    'Number of active workspaces',
    registry=REGISTRY
)

# Application info
app_info = Info('vm_api_application', 'VM-API application information', registry=REGISTRY)


def setup_metrics(app: FastAPI) -> Instrumentator:
    """
    Setup Prometheus metrics instrumentation for FastAPI application

    Args:
        app: FastAPI application instance

    Returns:
        Instrumentator instance
    """

    # Create instrumentator with custom registry
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        excluded_handlers=[],  # No need to exclude since we're not exposing /metrics
        inprogress_name="vm_api_http_requests_inprogress",
        inprogress_labels=True,
        registry=REGISTRY,
    )

    # Add default metrics
    instrumentator.add(
        metrics.request_size(
            should_include_handler=True,
            should_include_method=True,
            should_include_status=True,
            metric_name="vm_api_http_request_size_bytes",
            metric_doc="Size of HTTP requests in bytes",
        )
    )

    instrumentator.add(
        metrics.response_size(
            should_include_handler=True,
            should_include_method=True,
            should_include_status=True,
            metric_name="vm_api_http_response_size_bytes",
            metric_doc="Size of HTTP responses in bytes",
        )
    )

    instrumentator.add(
        metrics.latency(
            should_include_handler=True,
            should_include_method=True,
            should_include_status=True,
            metric_name="vm_api_http_request_duration_seconds",
            metric_doc="Duration of HTTP requests in seconds",
        )
    )

    instrumentator.add(
        metrics.requests(
            should_include_handler=True,
            should_include_method=True,
            should_include_status=True,
            metric_name="vm_api_http_requests_total",
            metric_doc="Total number of HTTP requests",
        )
    )

    # Instrument the app (collects metrics but does NOT expose /metrics endpoint)
    # We use push-based metrics to Pushgateway, so no /metrics endpoint is needed
    instrumentator.instrument(app)
    # Note: NOT calling instrumentator.expose(app) to avoid exposing /metrics endpoint

    # Set application info
    app_info.info({
        'version': '1.0.0',
        'python_version': '3.12',
        'framework': 'FastAPI'
    })

    logger.info("Prometheus metrics instrumentation setup complete")

    return instrumentator


async def push_metrics_to_gateway():
    """
    Background task to push metrics to Pushgateway
    Similar to how Promtail pushes logs to Loki
    """
    pushgateway_url = os.getenv("PUSHGATEWAY_URL", "pushgateway:9091")
    job_name = "vm-api"
    grouping_key = {
        "instance": os.getenv("HOSTNAME", "localhost"),
        "environment": os.getenv("DEPLOY_ENV", "local")
    }

    while True:
        try:
            # Push metrics to Pushgateway
            push_to_gateway(
                pushgateway_url,
                job=job_name,
                registry=REGISTRY,
                grouping_key=grouping_key
            )
            logger.debug(f"Pushed metrics to Pushgateway at {pushgateway_url}")
        except Exception as e:
            logger.error(f"Failed to push metrics to Pushgateway: {e}")

        # Push every 15 seconds (same as Prometheus scrape interval)
        await asyncio.sleep(15)
