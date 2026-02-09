"""
LangChain tools for RCA agent to interact with logs and metrics services.
"""

import logging
from typing import Optional

from langchain.tools import tool

from app.datasources.service import datasources_service
from app.log.models import TimeRange as LogTimeRange
from app.log.service import logs_service
from app.metrics.models import TimeRange as MetricTimeRange
from app.metrics.service import metrics_service

logger = logging.getLogger(__name__)


def _format_logs_response(response, limit: int = 50) -> str:
    """Format log query response for LLM consumption."""
    try:
        # Response is already a LogQueryResponse object
        if not response.data or not response.data.result:
            return "No logs found for the specified criteria."

        logs = []
        count = 0
        for stream in response.data.result:
            stream_labels = stream.stream or {}
            service = stream_labels.get("job", "unknown")

            for timestamp, message in stream.values or []:
                if count >= limit:
                    break
                # Format timestamp (Loki returns nanosecond precision)
                ts_seconds = int(timestamp) // 1_000_000_000
                logs.append(f"[{service}] [{ts_seconds}] {message}")
                count += 1

            if count >= limit:
                break

        summary = f"Found {count} log entries:\n\n" + "\n".join(logs)
        if count >= limit:
            summary += (
                f"\n\n(Showing first {limit} entries. More logs may be available.)"
            )

        return summary

    except Exception as e:
        logger.error(f"Error formatting logs: {e}")
        return f"Error parsing log response: {str(e)}"


def _format_metrics_response(response) -> str:
    """Format metrics query response for LLM consumption"""
    try:
        # Response is a RangeMetricResponse object
        if not response.result:
            return "No metrics data found for the specified criteria."

        metric_name = response.metric_name or "metric"

        formatted = []
        for series in response.result:
            labels = series.metric or {}
            values = series.values or []

            if not values:
                continue

            # Extract service/job label
            service = labels.get("job", "unknown")

            # Calculate statistics from MetricValue objects
            vals = [float(v.value) for v in values if v.value is not None]
            if vals:
                latest = vals[-1]
                avg = sum(vals) / len(vals)
                max_val = max(vals)
                min_val = min(vals)

                formatted.append(
                    f"Service: {service}\n"
                    f"  Latest: {latest:.2f}\n"
                    f"  Average: {avg:.2f}\n"
                    f"  Max: {max_val:.2f}\n"
                    f"  Min: {min_val:.2f}\n"
                    f"  Data points: {len(vals)}"
                )

        if formatted:
            return f"Metrics for '{metric_name}':\n\n" + "\n\n".join(formatted)
        else:
            return "Metrics data is empty or invalid."

    except Exception as e:
        logger.error(f"Error formatting metrics: {e}")
        return f"Error parsing metrics response: {str(e)}"


@tool
async def fetch_logs_tool(
    service_name: str,
    workspace_id: str,
    search_term: Optional[str] = None,
    start: str = "now-30m",
    end: str = "now",
    limit: int = 100,
    service_label_key: Optional[str] = None,
) -> str:
    """
    Fetch logs from a specific service with optional text search.

    The correct Loki label key is auto-discovered — just provide the service name.

    Args:
        service_name: The service name to fetch logs for (e.g., 'auth', 'marketplace')
        workspace_id: Workspace identifier (automatically provided from job context)
        search_term: Optional text to search for in logs (e.g., 'timeout', 'error', 'failed')
        start: Start time - use relative format like 'now-30m', 'now-1h', 'now-6h' (default: 'now-30m')
        end: End time - typically 'now' (default: 'now')
        limit: Maximum number of log entries to return (default: 100)
        service_label_key: Optional override for the Loki label key (auto-discovered if not provided)

    Returns:
        Formatted log entries with timestamps and messages

    Example:
        fetch_logs_tool(service_name="auth", start="now-1h")
        fetch_logs_tool(service_name="marketplace", search_term="timeout", start="now-6h")
    """
    try:
        time_range = LogTimeRange(start=start, end=end)

        if search_term:
            # Use search logs method
            response = await logs_service.search_logs(
                workspace_id=workspace_id,
                search_term=search_term,
                service_name=service_name,
                time_range=time_range,
                limit=limit,
                service_label_key=service_label_key,
            )
        else:
            # Use service logs method
            response = await logs_service.get_logs_by_service(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
                limit=limit,
                service_label_key=service_label_key,
            )

        return _format_logs_response(response, limit=50)

    except ValueError as e:
        return f"Configuration error: {str(e)}"
    except Exception as e:
        logger.error(f"Error in fetch_logs_tool: {e}")
        return f"Error fetching logs: {str(e)}"


@tool
async def fetch_error_logs_tool(
    workspace_id: str,
    service_name: Optional[str] = None,
    start: str = "now-30m",
    end: str = "now",
    limit: int = 100,
    service_label_key: Optional[str] = None,
) -> str:
    """
    Fetch ERROR-level logs to quickly identify failures and issues.

    Filters logs containing error keywords (case-insensitive).
    The correct Loki label key is auto-discovered — just provide the service name.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        service_name: Optional service name to filter by (if None, searches ALL services)
        start: Start time in relative format (default: 'now-30m')
        end: End time (default: 'now')
        limit: Maximum number of entries (default: 100)
        service_label_key: Optional override for the Loki label key (auto-discovered if not provided)

    Returns:
        Error logs with timestamps, service names, and error messages

    Example:
        fetch_error_logs_tool(service_name="auth", start="now-1h")
        fetch_error_logs_tool(start="now-6h")  # all services
    """
    try:
        time_range = LogTimeRange(start=start, end=end)

        response = await logs_service.get_error_logs(
            workspace_id=workspace_id,
            service_name=service_name,
            time_range=time_range,
            limit=limit,
            service_label_key=service_label_key,
        )

        return _format_logs_response(response, limit=50)

    except ValueError as e:
        return f"Configuration error: {str(e)}"
    except Exception as e:
        logger.error(f"Error in fetch_error_logs_tool: {e}")
        return f"Error fetching error logs: {str(e)}"


@tool
async def fetch_cpu_metrics_tool(
    workspace_id: str,
    service_name: Optional[str] = None,
    start_time: str = "now-1h",
    end_time: str = "now",
    step: str = "60s",
) -> str:
    """
    Get CPU usage metrics for a service over time.

    ⚠️ IMPORTANT: Use ACTUAL service name you discovered from logs.
    NEVER use placeholder names. If you don't have a service name, call without it to get all services.

    Use this to investigate performance degradation, resource saturation, or scaling issues.
    Returns CPU usage as a percentage.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        service_name: ACTUAL service name from logs (if None, gets all services)
        start_time: Start time like 'now-1h', 'now-6h' (default: 'now-1h')
        end_time: End time (default: 'now')
        step: Query resolution - '60s' for 1-min intervals, '300s' for 5-min (default: '60s')

    Returns:
        CPU usage statistics (latest, average, max, min) for ACTUAL services
    """
    try:
        time_range = MetricTimeRange(start=start_time, end=end_time, step=step)

        response = await metrics_service.get_cpu_metrics(
            workspace_id=workspace_id,
            service_name=service_name,
            time_range=time_range,
        )

        return _format_metrics_response(response)

    except ValueError as e:
        return f"Configuration error: {str(e)}"
    except Exception as e:
        logger.error(f"Error in fetch_cpu_metrics_tool: {e}")
        return f"Error fetching CPU metrics: {str(e)}"


@tool
async def fetch_memory_metrics_tool(
    workspace_id: str,
    service_name: Optional[str] = None,
    start_time: str = "now-1h",
    end_time: str = "now",
    step: str = "60s",
) -> str:
    """
    Get memory usage metrics for a service over time.

    ⚠️ IMPORTANT: Use ACTUAL service name you discovered from logs.
    NEVER use placeholder names.

    Use this to detect memory leaks, OOM issues, or resource constraints.
    Returns memory usage in megabytes (MB).

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        service_name: ACTUAL service name from logs
        start_time: Start time (default: 'now-1h')
        end_time: End time (default: 'now')
        step: Query resolution (default: '60s')

    Returns:
        Memory usage statistics in MB for ACTUAL services
    """
    try:
        time_range = MetricTimeRange(start=start_time, end=end_time, step=step)

        response = await metrics_service.get_memory_metrics(
            workspace_id=workspace_id,
            service_name=service_name,
            time_range=time_range,
        )

        return _format_metrics_response(response)

    except ValueError as e:
        return f"Configuration error: {str(e)}"
    except Exception as e:
        logger.error(f"Error in fetch_memory_metrics_tool: {e}")
        return f"Error fetching memory metrics: {str(e)}"


@tool
async def fetch_http_latency_tool(
    workspace_id: str,
    service_name: Optional[str] = None,
    percentile: float = 0.95,
    start_time: str = "now-1h",
    end_time: str = "now",
    step: str = "60s",
) -> str:
    """
    Get HTTP request latency metrics at specified percentile.

    ⚠️ IMPORTANT: Use ACTUAL service name you discovered from logs.
    NEVER use placeholder names.

    Use this to investigate slow response times, API performance issues, or latency spikes.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        service_name: ACTUAL service name from logs
        percentile: Latency percentile - 0.50 (p50/median), 0.95 (p95), 0.99 (p99) (default: 0.95)
        start_time: Start time (default: 'now-1h')
        end_time: End time (default: 'now')
        step: Query resolution (default: '60s')

    Returns:
        HTTP latency statistics at the specified percentile for ACTUAL services
    """
    try:
        time_range = MetricTimeRange(start=start_time, end=end_time, step=step)

        response = await metrics_service.get_http_latency_metrics(
            workspace_id=workspace_id,
            service_name=service_name,
            time_range=time_range,
            percentile=percentile,
        )

        return _format_metrics_response(response)

    except ValueError as e:
        return f"Configuration error: {str(e)}"
    except Exception as e:
        logger.error(f"Error in fetch_http_latency_tool: {e}")
        return f"Error fetching latency metrics: {str(e)}"


@tool
async def fetch_metrics_tool(
    metric_type: str,
    workspace_id: str,
    service_name: Optional[str] = None,
    start_time: str = "now-1h",
    end_time: str = "now",
    step: str = "60s",
) -> str:
    """
    Fetch various types of metrics for comprehensive analysis.

    ⚠️ IMPORTANT: Use ACTUAL service name you discovered from logs, or omit service_name to get all services.
    NEVER use placeholder names.

    Use this for additional metrics beyond CPU, memory, and latency.

    Args:
        metric_type: Type of metric - 'http_requests', 'errors', 'throughput', 'availability'
        workspace_id: Workspace identifier (automatically provided from job context)
        service_name: ACTUAL service name from logs (if None, queries all services)
        start_time: Start time (default: 'now-1h')
        end_time: End time (default: 'now')
        step: Query resolution (default: '60s')

    Returns:
        Metrics data formatted for analysis showing ACTUAL service names
    """
    try:
        time_range = MetricTimeRange(start=start_time, end=end_time, step=step)

        # Map metric types to service methods
        if metric_type == "http_requests":
            response = await metrics_service.get_http_request_metrics(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
            )
        elif metric_type == "errors":
            response = await metrics_service.get_error_rate_metrics(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
            )
        elif metric_type == "throughput":
            response = await metrics_service.get_throughput_metrics(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
            )
        elif metric_type == "availability":
            response = await metrics_service.get_availability_metrics(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
            )
        else:
            return f"Unknown metric_type '{metric_type}'. Valid types: http_requests, errors, throughput, availability"

        return _format_metrics_response(response)

    except ValueError as e:
        return f"Configuration error: {str(e)}"
    except Exception as e:
        logger.error(f"Error in fetch_metrics_tool: {e}")
        return f"Error fetching {metric_type} metrics: {str(e)}"


@tool
async def get_datasources_tool(
    workspace_id: str,
) -> str:
    """
    Get all available Grafana datasources for the workspace.

    Use this tool to discover what datasources are available for querying logs and metrics.
    This is useful when you need to identify datasource UIDs for label queries or when
    exploring what data sources are configured.

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)

    Returns:
        List of datasources with their IDs, names, types, and whether they're default

    Example usage:
        get_datasources_tool()
    """
    try:
        datasources = await datasources_service.get_datasources(workspace_id)

        if not datasources:
            return "No datasources found for this workspace."

        formatted = ["Available datasources:\n"]
        for ds in datasources:
            ds_type = ds.get("type", "unknown")
            ds_name = ds.get("name", "unnamed")
            ds_uid = ds.get("uid", "no-uid")
            is_default = " (default)" if ds.get("isDefault") else ""

            formatted.append(
                f"- Name: {ds_name}\n  Type: {ds_type}\n  UID: {ds_uid}{is_default}"
            )

        return "\n\n".join(formatted)

    except ValueError as e:
        return f"Configuration error: {str(e)}"
    except Exception as e:
        logger.error(f"Error in get_datasources_tool: {e}")
        return f"Error fetching datasources: {str(e)}"


@tool
async def get_labels_tool(
    datasource_uid: str,
    workspace_id: str,
) -> str:
    """
    Get all available label keys from a specific datasource (Loki or Prometheus).

    Use this tool to discover what labels are available for filtering logs or metrics.
    Labels are key-value pairs used to identify and filter time series data.
    Common labels include: job, instance, namespace, pod, service, etc.

    You must first use get_datasources_tool to find the datasource_uid.

    Args:
        datasource_uid: The UID of the datasource (get from get_datasources_tool)
        workspace_id: Workspace identifier (automatically provided from job context)

    Returns:
        List of available label keys for the datasource

    Example usage:
        # First get datasources to find the UID
        get_datasources_tool()
        # Then get labels for a specific datasource
        get_labels_tool(datasource_uid="abc123xyz")
    """
    try:
        response = await datasources_service.get_labels(workspace_id, datasource_uid)

        if response.status != "success" or not response.data:
            return f"No labels found for datasource {datasource_uid}. Status: {response.status}"

        labels = response.data
        formatted = [f"Available labels for datasource {datasource_uid}:\n"]

        # Group labels for better readability
        common_labels = [
            label
            for label in labels
            if label in ["job", "instance", "namespace", "pod", "service", "container"]
        ]
        other_labels = [label for label in labels if label not in common_labels]

        if common_labels:
            formatted.append("Common labels:")
            formatted.append(", ".join(common_labels))

        if other_labels:
            formatted.append("\nOther labels:")
            formatted.append(", ".join(other_labels))

        formatted.append(f"\n\nTotal: {len(labels)} labels available")
        formatted.append(
            "\nUse get_label_values_tool to see possible values for any label."
        )

        return "\n".join(formatted)

    except ValueError as e:
        return f"Configuration error: {str(e)}"
    except Exception as e:
        logger.error(f"Error in get_labels_tool: {e}")
        return f"Error fetching labels: {str(e)}"


@tool
async def get_label_values_tool(
    datasource_uid: str,
    label_name: str,
    workspace_id: str,
) -> str:
    """
    Get all possible values for a specific label in a datasource.

    Use this tool to discover what values exist for a label. For example, if you want to
    know what services are available, get values for the "job" label. If you want to know
    what namespaces exist, get values for the "namespace" label.

    This helps you construct accurate queries and understand your infrastructure.

    You must first use get_labels_tool to find available label names.

    Args:
        datasource_uid: The UID of the datasource (get from get_datasources_tool)
        label_name: The label key to get values for (get from get_labels_tool)
        workspace_id: Workspace identifier (automatically provided from job context)

    Returns:
        List of all possible values for the specified label

    Example usage:
        # First get datasources, then labels, then label values
        get_datasources_tool()
        get_labels_tool(datasource_uid="abc123xyz")
        get_label_values_tool(datasource_uid="abc123xyz", label_name="job")
    """
    try:
        response = await datasources_service.get_label_values(
            workspace_id, datasource_uid, label_name
        )

        if response.status != "success" or not response.data:
            return f"No values found for label '{label_name}' in datasource {datasource_uid}. Status: {response.status}"

        values = response.data
        formatted = [
            f"Values for label '{label_name}' in datasource {datasource_uid}:\n"
        ]

        # If there are many values, show first 50 and indicate there are more
        if len(values) > 50:
            formatted.append(", ".join(values[:50]))
            formatted.append(f"\n\n... and {len(values) - 50} more values")
            formatted.append(f"\nTotal: {len(values)} values")
        else:
            formatted.append(", ".join(values))
            formatted.append(f"\n\nTotal: {len(values)} values")

        return "\n".join(formatted)

    except ValueError as e:
        return f"Configuration error: {str(e)}"
    except Exception as e:
        logger.error(f"Error in get_label_values_tool: {e}")
        return f"Error fetching label values: {str(e)}"
