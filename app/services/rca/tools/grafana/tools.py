"""
LangChain tools for RCA agent to interact with logs and metrics services
"""
import logging
from typing import Optional
from langchain.tools import tool

from app.log.service import logs_service
from app.log.models import TimeRange as LogTimeRange
from app.metrics.service import metrics_service
from app.metrics.models import TimeRange as MetricTimeRange

logger = logging.getLogger(__name__)


def _format_logs_response(response, limit: int = 50) -> str:
    """Format log query response for LLM consumption"""
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
            summary += f"\n\n(Showing first {limit} entries. More logs may be available.)"

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
) -> str:
    """
    Fetch logs from a specific service with optional text search.

    ⚠️ IMPORTANT: You must provide an ACTUAL service name you discovered from logs.
    NEVER assume or guess service names. If you don't have a service name yet,
    use fetch_error_logs_tool WITHOUT service_name to discover services first.

    Use this tool to investigate log patterns, search for specific errors, or examine service behavior.

    Args:
        service_name: ACTUAL service name from logs (NOT "xyz" or any placeholder)
        workspace_id: Workspace identifier (automatically provided from job context)
        search_term: Optional text to search for in logs (e.g., 'timeout', 'error', 'failed')
        start: Start time - use relative format like 'now-30m', 'now-1h', 'now-6h' (default: 'now-30m')
        end: End time - typically 'now' (default: 'now')
        limit: Maximum number of log entries to return (default: 100)

    Returns:
        Formatted log entries with timestamps and messages

    Example usage pattern (NOT real service names):
        # First discover service name from error logs
        # Then use that ACTUAL service name here
        fetch_logs_tool(service_name="<ACTUAL_SERVICE_FROM_LOGS>", search_term="connection timeout", start="now-1h")
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
            )
        else:
            # Use service logs method
            response = await logs_service.get_logs_by_service(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
                limit=limit,
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
) -> str:
    """
    Fetch ERROR-level logs to quickly identify failures and issues.

    ⚠️ CRITICAL: This is typically the FIRST tool to use when investigating problems.
    Call this WITHOUT service_name parameter to discover ALL services experiencing errors.
    The output will show you ACTUAL service names which you can use in subsequent queries.

    Filters logs containing error keywords (case-insensitive).

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        service_name: Optional ACTUAL service name from previous log output (if None, searches ALL services - RECOMMENDED for discovery)
        start: Start time in relative format (default: 'now-30m')
        end: End time (default: 'now')
        limit: Maximum number of entries (default: 100)

    Returns:
        Error logs with timestamps, ACTUAL service names, and error messages

    Example usage patterns (NOT real service names):
        # First call - discover services (NO service_name parameter):
        fetch_error_logs_tool(start="now-1h")

        # After discovering service "serviceDesk" from above output:
        fetch_error_logs_tool(service_name="serviceDesk", start="now-1h")
    """
    try:
        time_range = LogTimeRange(start=start, end=end)

        response = await logs_service.get_error_logs(
            workspace_id=workspace_id,
            service_name=service_name,
            time_range=time_range,
            limit=limit,
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

    Example usage pattern (NOT real service names):
        # Use ACTUAL service name discovered from error logs
        fetch_cpu_metrics_tool(service_name="<ACTUAL_SERVICE>", start_time="now-2h")
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

    Example usage pattern (NOT real service names):
        # Use ACTUAL service name discovered from error logs
        fetch_memory_metrics_tool(service_name="<ACTUAL_SERVICE>", start_time="now-3h")
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

    Example usage pattern (NOT real service names):
        # Use ACTUAL service name discovered from error logs
        fetch_http_latency_tool(service_name="<ACTUAL_SERVICE>", percentile=0.99, start_time="now-2h")
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

    Example usage pattern (NOT real service names):
        # Use ACTUAL service name discovered from error logs, or omit to see all services
        fetch_metrics_tool(metric_type="errors", service_name="<ACTUAL_SERVICE>", start_time="now-3h")
        # OR discover all services experiencing errors:
        fetch_metrics_tool(metric_type="errors", start_time="now-3h")
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
