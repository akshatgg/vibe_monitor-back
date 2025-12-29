"""
LangChain tools for RCA agent to interact with Datadog Logs, Metrics, and Events
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from langchain.tools import tool

from app.core.database import AsyncSessionLocal
from app.datadog.Logs.schemas import (
    ListLogsRequest,
    ListServicesRequest,
    SearchLogsRequest,
)
from app.datadog.Logs.service import datadog_logs_service
from app.datadog.Metrics.schemas import (
    EventsSearchRequest,
    QueryTimeseriesRequest,
    SimpleQueryRequest,
)
from app.datadog.Metrics.service import datadog_metrics_service

logger = logging.getLogger(__name__)


# ============================================================================
# Response Formatters
# ============================================================================


def _format_logs_search_response(response, limit: int = 50) -> str:
    """Format Datadog logs search response for LLM consumption"""
    try:
        if not response.data:
            return "No log entries found for the specified query."

        logs = []
        for log in response.data[:limit]:
            # Extract timestamp and message
            timestamp_str = "N/A"
            if log.attributes and log.attributes.timestamp:
                timestamp = datetime.fromisoformat(
                    log.attributes.timestamp.replace("Z", "+00:00")
                )
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

            message = "No message"
            if log.attributes and log.attributes.message:
                message = log.attributes.message

            # Include service and status if available
            service = (
                log.attributes.service
                if log.attributes and log.attributes.service
                else "unknown"
            )
            status = (
                log.attributes.status
                if log.attributes and log.attributes.status
                else "info"
            )

            logs.append(f"[{timestamp_str}] [{status.upper()}] [{service}] {message}")

        count = len(logs)
        summary = (
            f"Found {response.totalCount} log entries (showing {count}):\n\n"
            + "\n".join(logs)
        )

        if response.totalCount > limit:
            summary += f"\n\n(Showing first {limit} entries. {response.totalCount - limit} more logs available.)"

        if response.meta:
            summary += f"\n\nQuery elapsed time: {response.meta.elapsed}ms"

        return summary

    except Exception as e:
        logger.error(f"Error formatting logs search response: {e}")
        return f"Error parsing log entries: {str(e)}"


def _format_logs_list_response(response, limit: int = 50) -> str:
    """Format Datadog simplified logs list response for LLM consumption"""
    try:
        if not response.logs:
            return "No log entries found for the specified criteria."

        logs = []
        for log in response.logs[:limit]:
            timestamp_str = "N/A"
            if log.timestamp:
                timestamp = datetime.fromisoformat(log.timestamp.replace("Z", "+00:00"))
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

            message = log.message or "No message"
            service = log.service or "unknown"
            status = log.status or "info"

            logs.append(f"[{timestamp_str}] [{status.upper()}] [{service}] {message}")

        count = len(logs)
        summary = (
            f"Found {response.totalCount} log entries (showing {count}):\n\n"
            + "\n".join(logs)
        )

        if response.totalCount > limit:
            summary += f"\n\n(Showing first {limit} entries. {response.totalCount - limit} more logs available.)"

        return summary

    except Exception as e:
        logger.error(f"Error formatting logs list response: {e}")
        return f"Error parsing log entries: {str(e)}"


def _format_services_response(response) -> str:
    """Format Datadog services list response for LLM consumption"""
    try:
        if not response.services:
            return "No services found in the logs."

        services_str = ", ".join(response.services)
        summary = f"Found {response.totalCount} services:\n\n{services_str}"

        return summary

    except Exception as e:
        logger.error(f"Error formatting services response: {e}")
        return f"Error parsing services list: {str(e)}"


def _format_simple_metrics_response(response) -> str:
    """Format Datadog simple metrics query response for LLM consumption"""
    try:
        if not response.points:
            return f"No data points found for query '{response.query}'."

        # Extract values for statistics
        values = [dp.value for dp in response.points if dp.value is not None]

        if not values:
            return f"No valid data points found for query '{response.query}'."

        latest = values[-1] if values else 0
        avg = sum(values) / len(values) if values else 0
        max_val = max(values) if values else 0
        min_val = min(values) if values else 0

        # Format timestamps for first and last datapoint
        first_time = datetime.fromtimestamp(
            response.points[0].timestamp / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")
        last_time = datetime.fromtimestamp(
            response.points[-1].timestamp / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

        formatted = (
            f"📊 Metrics for query **{response.query}** (from {first_time} to {last_time}):\n\n"
            f"  Latest: {latest:.2f}\n"
            f"  Average: {avg:.2f}\n"
            f"  Maximum: {max_val:.2f}\n"
            f"  Minimum: {min_val:.2f}\n"
            f"  Data points: {len(values)}\n"
        )

        # Add recent datapoints
        formatted += "\nRecent data points:\n"
        for dp in response.points[-10:]:  # Last 10 datapoints
            ts = datetime.fromtimestamp(dp.timestamp / 1000, tz=timezone.utc).strftime(
                "%H:%M:%S"
            )
            val = dp.value if dp.value is not None else 0
            formatted += f"  {ts}: {val:.2f}\n"

        return formatted

    except Exception as e:
        logger.error(f"Error formatting simple metrics response: {e}")
        return f"Error parsing metrics data: {str(e)}"


def _format_timeseries_response(response) -> str:
    """Format Datadog timeseries response for LLM consumption"""
    try:
        if (
            not response.data
            or not response.data.attributes
            or not response.data.attributes.series
        ):
            return "No timeseries data found."

        attrs = response.data.attributes
        times = attrs.times or []
        values = attrs.values or []

        if not times or not values:
            return "No data points available in timeseries response."

        # Calculate statistics from first series
        if values and len(values) > 0:
            series_values = [v for v in values[0] if v is not None]

            if not series_values:
                return "No valid data points in timeseries."

            latest = series_values[-1]
            avg = sum(series_values) / len(series_values)
            max_val = max(series_values)
            min_val = min(series_values)

            first_time = datetime.fromtimestamp(
                times[0] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S UTC")
            last_time = datetime.fromtimestamp(
                times[-1] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S UTC")

            formatted = (
                f"📊 Timeseries Data (from {first_time} to {last_time}):\n\n"
                f"  Latest: {latest:.2f}\n"
                f"  Average: {avg:.2f}\n"
                f"  Maximum: {max_val:.2f}\n"
                f"  Minimum: {min_val:.2f}\n"
                f"  Data points: {len(series_values)}\n"
                f"  Series count: {len(attrs.series)}\n"
            )

            # Add recent datapoints
            formatted += "\nRecent data points:\n"
            recent_count = min(10, len(times))
            for i in range(len(times) - recent_count, len(times)):
                ts = datetime.fromtimestamp(times[i] / 1000, tz=timezone.utc).strftime(
                    "%H:%M:%S"
                )
                val = values[0][i] if values[0][i] is not None else 0
                formatted += f"  {ts}: {val:.2f}\n"

            return formatted

        return "Unable to extract data from timeseries response."

    except Exception as e:
        logger.error(f"Error formatting timeseries response: {e}")
        return f"Error parsing timeseries data: {str(e)}"


def _format_events_response(response, limit: int = 20) -> str:
    """Format Datadog events search response for LLM consumption"""
    try:
        if not response.events:
            return "No events found for the specified time range."

        events = []
        for event in response.events[:limit]:
            timestamp_str = "N/A"
            if event.date_happened:
                timestamp = datetime.fromtimestamp(event.date_happened, tz=timezone.utc)
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

            title = event.title or "No title"
            text = event.text or "No description"
            alert_type = event.alert_type or "info"
            source = event.source or "unknown"

            # Truncate long event text
            if len(text) > 200:
                text = text[:200] + "..."

            events.append(
                f"[{timestamp_str}] [{alert_type.upper()}] {title}\n  Source: {source}\n  {text}"
            )

        count = len(events)
        summary = (
            f"Found {response.totalCount} events (showing {count}):\n\n"
            + "\n\n".join(events)
        )

        if response.totalCount > limit:
            summary += f"\n\n(Showing first {limit} events. {response.totalCount - limit} more events available.)"

        return summary

    except Exception as e:
        logger.error(f"Error formatting events response: {e}")
        return f"Error parsing events: {str(e)}"


def _format_tags_response(response) -> str:
    """Format Datadog tags list response for LLM consumption"""
    try:
        if not response.tags:
            return "No tags found."

        summary = f"Found {response.totalTags} unique tags:\n\n"

        # Show tags by category
        if response.tagsByCategory:
            summary += "Tags by category:\n"
            for category, values in sorted(response.tagsByCategory.items()):
                summary += f"\n  {category}:\n"
                for value in sorted(values[:10]):  # Show first 10 per category
                    summary += f"    - {value}\n"
                if len(values) > 10:
                    summary += f"    ... and {len(values) - 10} more\n"
        else:
            # Show flat tag list
            summary += "\n".join(f"  - {tag}" for tag in sorted(response.tags[:50]))
            if len(response.tags) > 50:
                summary += f"\n\n(Showing first 50 tags. {len(response.tags) - 50} more available.)"

        return summary

    except Exception as e:
        logger.error(f"Error formatting tags response: {e}")
        return f"Error parsing tags: {str(e)}"


# ============================================================================
# Log Tools
# ============================================================================


@tool
async def search_datadog_logs_tool(
    workspace_id: str,
    query: str,
    start_hours_ago: int = 1,
    limit: int = 50,
) -> str:
    """
    Search Datadog logs using Datadog log search syntax.

    Use this tool for searching logs with complex filtering and analysis.
    Essential for investigating errors, exceptions, and application behavior.

    Use this tool to:
    - Find logs containing specific error messages or keywords
    - Filter logs by service, status, or custom attributes
    - Search for request IDs, trace IDs, or correlation IDs
    - Investigate application errors and exceptions

    Query syntax examples:
    - "service:my-app" - Filter by service name
    - "status:error" - Filter by status level (error, warn, info, debug)
    - "service:api status:error" - Multiple filters (AND)
    - "@http.status_code:500" - Filter by custom attribute
    - "error OR exception" - Text search with OR
    - "service:api -host:excluded" - Exclude with minus

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        query: Datadog log search query string
        start_hours_ago: How many hours back to search (default: 1)
        limit: Maximum number of log entries to return (default: 50)

    Returns:
        Log entries matching the query with timestamps, service, status, and messages

    Example usage:
        search_datadog_logs_tool(
            workspace_id="<workspace-id>",
            query="service:api status:error",
            start_hours_ago=2
        )
    """
    try:
        # Calculate time range in milliseconds
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = SearchLogsRequest(
                query=query,
                **{
                    "from": int(start_time.timestamp() * 1000),
                    "to": int(end_time.timestamp() * 1000),
                },
                sort="desc",
                page_limit=limit,
            )

            response = await datadog_logs_service.search_logs(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_logs_search_response(response, limit=limit)

    except Exception as e:
        logger.error(f"Error in search_datadog_logs_tool: {e}")
        return f"Failed to search logs: {str(e)}"


@tool
async def list_datadog_logs_tool(
    workspace_id: str,
    service_name: Optional[str] = None,
    status: Optional[str] = None,
    start_hours_ago: int = 1,
    limit: int = 50,
) -> str:
    """
    List Datadog logs with simplified filtering (returns simplified format).

    Simpler alternative to search_datadog_logs_tool with basic filtering options.
    Use this for quick log review without complex query syntax.

    Use this tool to:
    - Get recent logs from a specific service
    - Filter logs by status level
    - Quick log review and monitoring

    Status levels: error, warn, info, debug

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        service_name: Optional service name to filter by
        status: Optional status level to filter by (error, warn, info, debug)
        start_hours_ago: How many hours back to search (default: 1)
        limit: Maximum number of log entries to return (default: 50)

    Returns:
        Simplified log entries with timestamps, service, status, and messages

    Example usage:
        list_datadog_logs_tool(
            workspace_id="<workspace-id>",
            service_name="api-service",
            status="error",
            start_hours_ago=2
        )
    """
    try:
        # Calculate time range in milliseconds
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = ListLogsRequest(
                **{
                    "from": int(start_time.timestamp() * 1000),
                    "to": int(end_time.timestamp() * 1000),
                },
                service=service_name,
                status=status,
                limit=limit,
            )

            response = await datadog_logs_service.list_logs(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_logs_list_response(response, limit=limit)

    except Exception as e:
        logger.error(f"Error in list_datadog_logs_tool: {e}")
        return f"Failed to list logs: {str(e)}"


@tool
async def list_datadog_log_services_tool(
    workspace_id: str,
    start_hours_ago: int = 24,
) -> str:
    """
    List all services that have logged data in Datadog.

    Use this tool to discover what services are available for log analysis.
    Helpful for understanding the service landscape and identifying which services to investigate.

    Use this tool to:
    - Discover available services in the environment
    - Understand service naming conventions
    - Identify services to investigate during RCA

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        start_hours_ago: How many hours back to look for services (default: 24, can be extended to 48, 72, 168 for 1 week, or more)

    Returns:
        List of service names that have logged data

    Example usage:
        # Look back 24 hours (default)
        list_datadog_log_services_tool(workspace_id="<workspace-id>")

        # Look back 1 week (168 hours) if no services found
        list_datadog_log_services_tool(workspace_id="<workspace-id>", start_hours_ago=168)
    """
    try:
        # Calculate time range in milliseconds
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = ListServicesRequest(
                **{
                    "from": int(start_time.timestamp() * 1000),
                    "to": int(end_time.timestamp() * 1000),
                }
            )

            response = await datadog_logs_service.list_services(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_services_response(response)

    except Exception as e:
        logger.error(f"Error in list_datadog_log_services_tool: {e}")
        return f"Failed to list services: {str(e)}"


# ============================================================================
# Metrics Tools
# ============================================================================


@tool
async def query_datadog_metrics_tool(
    workspace_id: str,
    metric_query: str,
    start_hours_ago: int = 1,
) -> str:
    """
    Query Datadog metrics using Datadog metric query syntax.

    Use this tool for querying metrics and analyzing performance data.
    Essential for investigating performance issues, resource utilization, and trends.

    Use this tool to:
    - Monitor application performance metrics
    - Track infrastructure metrics (CPU, memory, disk, network)
    - Analyze custom application metrics
    - Investigate performance degradation

    Common metrics and query patterns:
    - System metrics:
      - "avg:system.cpu.user{*}" - Average CPU user time
      - "avg:system.mem.used{*}" - Average memory usage
      - "avg:system.disk.used{*}" - Average disk usage
    - AWS metrics:
      - "avg:aws.ec2.cpuutilization{*}" - EC2 CPU utilization
      - "sum:aws.lambda.invocations{*}" - Lambda invocations
    - Custom metrics:
      - "avg:custom.api.response_time{service:api}" - API response time
      - "sum:custom.requests{*} by {endpoint}" - Requests by endpoint

    Aggregation functions: avg, sum, min, max, count

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        metric_query: Datadog metric query (e.g., "avg:system.cpu.user{*}")
        start_hours_ago: How many hours back to query (default: 1)

    Returns:
        Metric time series with latest, average, maximum, minimum values and recent data points

    Example usage:
        query_datadog_metrics_tool(
            workspace_id="<workspace-id>",
            metric_query="avg:system.cpu.user{service:api}",
            start_hours_ago=2
        )
    """
    try:
        # Calculate time range in milliseconds
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = SimpleQueryRequest(
                query=metric_query,
                from_timestamp=int(start_time.timestamp() * 1000),
                to_timestamp=int(end_time.timestamp() * 1000),
            )

            response = await datadog_metrics_service.query_simple(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_simple_metrics_response(response)

    except Exception as e:
        logger.error(f"Error in query_datadog_metrics_tool: {e}")
        return f"Failed to query metrics: {str(e)}"


@tool
async def query_datadog_timeseries_tool(
    workspace_id: str,
    metric_query: str,
    start_hours_ago: int = 1,
) -> str:
    """
    Query Datadog timeseries metrics (advanced format with full metadata).

    Use this tool for detailed timeseries metric analysis with complete metadata.
    Provides more detailed response than query_datadog_metrics_tool.

    Use this tool to:
    - Get detailed metric metadata and units
    - Analyze complex metric queries
    - Track metrics with specific grouping or filtering

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        metric_query: Datadog metric query (e.g., "avg:system.cpu.user{*}")
        start_hours_ago: How many hours back to query (default: 1)

    Returns:
        Detailed timeseries data with statistics and metadata

    Example usage:
        query_datadog_timeseries_tool(
            workspace_id="<workspace-id>",
            metric_query="avg:aws.ec2.cpuutilization{*}",
            start_hours_ago=2
        )
    """
    try:
        # Calculate time range in milliseconds
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = QueryTimeseriesRequest(
                query=metric_query,
                **{
                    "from": int(start_time.timestamp() * 1000),
                    "to": int(end_time.timestamp() * 1000),
                },
            )

            response = await datadog_metrics_service.query_timeseries(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_timeseries_response(response)

    except Exception as e:
        logger.error(f"Error in query_datadog_timeseries_tool: {e}")
        return f"Failed to query timeseries: {str(e)}"


@tool
async def search_datadog_events_tool(
    workspace_id: str,
    tags: Optional[str] = None,
    start_hours_ago: int = 24,
) -> str:
    """
    Search Datadog events (deployments, alerts, changes, annotations).

    Use this tool to find events that occurred during a time range.
    Events show what changed in your infrastructure - critical for RCA!

    Use this tool to:
    - Find deployments and code changes
    - Track alerts that fired or resolved
    - Investigate configuration changes
    - Correlate events with incidents

    Event types include:
    - Deployments and releases
    - Alerts fired/resolved
    - Configuration changes
    - Auto-scaling events
    - Host/container lifecycle events
    - Custom annotations

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        tags: Optional comma-separated tags to filter events (e.g., "env:prod,service:api")
        start_hours_ago: How many hours back to search (default: 24)

    Returns:
        List of events with timestamps, titles, descriptions, and sources

    Example usage:
        search_datadog_events_tool(
            workspace_id="<workspace-id>",
            tags="env:prod,service:api",
            start_hours_ago=12
        )
    """
    try:
        # Calculate time range in SECONDS
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = EventsSearchRequest(
                start=int(start_time.timestamp()),
                end=int(end_time.timestamp()),
                tags=tags,
            )

            response = await datadog_metrics_service.search_events(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_events_response(response)

    except Exception as e:
        logger.error(f"Error in search_datadog_events_tool: {e}")
        return f"Failed to search events: {str(e)}"


@tool
async def list_datadog_tags_tool(
    workspace_id: str,
) -> str:
    """
    List all available Datadog tags.

    Use this tool to discover what tags are available for filtering logs, metrics, and events.
    Helps understand the tagging strategy and find relevant filters.

    Use this tool to:
    - Discover available tags in the environment
    - Understand tag structure and categories
    - Find tags to use in other queries

    Tag categories typically include:
    - env: Environment (prod, staging, dev)
    - service: Service names
    - region: Geographic regions
    - host: Hostnames
    - container: Container identifiers

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)

    Returns:
        List of all tags organized by category

    Example usage:
        list_datadog_tags_tool(
            workspace_id="<workspace-id>"
        )
    """
    try:
        async with AsyncSessionLocal() as db:
            response = await datadog_metrics_service.list_tags(
                db=db, workspace_id=workspace_id
            )

        return _format_tags_response(response)

    except Exception as e:
        logger.error(f"Error in list_datadog_tags_tool: {e}")
        return f"Failed to list tags: {str(e)}"


# Export all tools
__all__ = [
    "search_datadog_logs_tool",
    "list_datadog_logs_tool",
    "list_datadog_log_services_tool",
    "query_datadog_metrics_tool",
    "query_datadog_timeseries_tool",
    "search_datadog_events_tool",
    "list_datadog_tags_tool",
]
