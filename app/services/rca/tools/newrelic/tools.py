"""
LangChain tools for RCA agent to interact with New Relic Logs and Metrics
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from langchain.tools import tool

from app.core.database import AsyncSessionLocal
from app.newrelic.Logs.schemas import FilterLogsRequest, QueryLogsRequest
from app.newrelic.Logs.service import newrelic_logs_service
from app.newrelic.Metrics.schemas import (
    GetInfraMetricsRequest,
    GetTimeSeriesRequest,
    QueryMetricsRequest,
)
from app.newrelic.Metrics.service import newrelic_metrics_service

logger = logging.getLogger(__name__)


# ============================================================================
# Response Formatters
# ============================================================================


def _format_logs_response(response, limit: int = 50) -> str:
    """Format New Relic logs response for LLM consumption"""
    try:
        if not response.logs:
            return "No log entries found for the specified query."

        logs = []
        for log in response.logs[:limit]:
            # Convert timestamp from milliseconds to datetime if available
            timestamp_str = "N/A"
            if log.timestamp:
                timestamp = datetime.fromtimestamp(
                    log.timestamp / 1000, tz=timezone.utc
                )
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

            message = log.message or "No message"
            logs.append(f"[{timestamp_str}] {message}")

        count = len(logs)
        summary = (
            f"Found {response.totalCount} log entries (showing {count}):\n\n"
            + "\n".join(logs)
        )

        if response.totalCount > limit:
            summary += f"\n\n(Showing first {limit} entries. {response.totalCount - limit} more logs available.)"

        return summary

    except Exception as e:
        logger.exception(f"Error formatting logs response: {e}")
        return f"Error parsing log entries: {str(e)}"


def _format_query_logs_response(response, limit: int = 50) -> str:
    """Format New Relic query logs response for LLM consumption"""
    try:
        if not response.results:
            return "Query completed but no results found."

        formatted_rows = []
        for row in response.results[:limit]:
            # Format each result as key-value pairs
            row_str = " | ".join([f"{k}: {v}" for k, v in row.items()])
            formatted_rows.append(row_str)

        summary = (
            f"Query completed successfully. Found {response.totalCount} results:\n\n"
        )
        summary += "\n".join(formatted_rows)

        if response.totalCount > limit:
            summary += (
                f"\n\n(Showing first {limit} results. Total: {response.totalCount})"
            )

        if response.metadata:
            event_types = response.metadata.get("eventTypes", [])
            if event_types:
                summary += f"\n\nEvent types: {', '.join(event_types)}"

        return summary

    except Exception as e:
        logger.exception(f"Error formatting query logs: {e}")
        return f"Error parsing query results: {str(e)}"


def _format_metrics_response(response, limit: int = 50) -> str:
    """Format New Relic metrics response for LLM consumption"""
    try:
        if not response.results:
            return "Query completed but no metric results found."

        formatted_rows = []
        for row in response.results[:limit]:
            # Format each metric result as key-value pairs
            row_str = " | ".join([f"{k}: {v}" for k, v in row.items()])
            formatted_rows.append(row_str)

        summary = f"Query completed successfully. Found {response.totalCount} metric results:\n\n"
        summary += "\n".join(formatted_rows)

        if response.totalCount > limit:
            summary += (
                f"\n\n(Showing first {limit} results. Total: {response.totalCount})"
            )

        return summary

    except Exception as e:
        logger.exception(f"Error formatting metrics response: {e}")
        return f"Error parsing metric results: {str(e)}"


def _format_time_series_response(response) -> str:
    """Format New Relic time series response for LLM consumption"""
    try:
        if not response.dataPoints:
            return f"No data points found for metric '{response.metricName}'."

        # Extract values for statistics
        values = [dp.value for dp in response.dataPoints if dp.value is not None]

        if not values:
            return f"No valid data points found for metric '{response.metricName}'."

        latest = values[-1] if values else 0
        avg = sum(values) / len(values) if values else 0
        max_val = max(values) if values else 0
        min_val = min(values) if values else 0

        # Format timestamps for first and last datapoint
        first_time = datetime.fromtimestamp(
            response.dataPoints[0].timestamp, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")
        last_time = datetime.fromtimestamp(
            response.dataPoints[-1].timestamp, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

        formatted = (
            f"📊 Metrics for **{response.metricName}** (from {first_time} to {last_time}):\n\n"
            f"  Latest: {latest:.2f}\n"
            f"  Average: {avg:.2f}\n"
            f"  Maximum: {max_val:.2f}\n"
            f"  Minimum: {min_val:.2f}\n"
            f"  Aggregation: {response.aggregation}\n"
            f"  Data points: {len(values)}\n"
        )

        # Add individual datapoints for detailed analysis
        formatted += "\nRecent data points:\n"
        for dp in response.dataPoints[-10:]:  # Last 10 datapoints
            ts = datetime.fromtimestamp(dp.timestamp, tz=timezone.utc).strftime(
                "%H:%M:%S"
            )
            val = dp.value if dp.value is not None else 0
            formatted += f"  {ts}: {val:.2f}\n"

        return formatted

    except Exception as e:
        logger.exception(f"Error formatting time series: {e}")
        return f"Error parsing time series data: {str(e)}"


# ============================================================================
# Log Tools
# ============================================================================


@tool
async def query_newrelic_logs_tool(
    workspace_id: str,
    nrql_query: str,
) -> str:
    """
    Query New Relic logs using NRQL (New Relic Query Language).

    Use this tool for advanced log queries with complex filtering, aggregation, and analysis.
    NRQL is powerful for analyzing patterns, counting occurrences, and extracting insights.

    Use this tool to:
    - Run complex NRQL queries on log data
    - Aggregate and analyze log patterns
    - Extract specific fields from structured logs
    - Calculate statistics over log data

    Common NRQL patterns:
    - Basic query: "SELECT * FROM Log WHERE message LIKE '%error%' SINCE 1 hour ago LIMIT 100"
    - Count errors: "SELECT count(*) FROM Log WHERE message LIKE '%ERROR%' SINCE 1 hour ago FACET host"
    - Parse fields: "SELECT message, timestamp FROM Log WHERE app_name = 'api-service' SINCE 30 minutes ago"

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        nrql_query: NRQL query string for logs

    Returns:
        Query results with log entries and metadata

    Example usage:
        query_newrelic_logs_tool(
            workspace_id="<workspace-id>",
            nrql_query="SELECT * FROM Log WHERE message LIKE '%timeout%' SINCE 1 hour ago LIMIT 50"
        )
    """
    try:
        async with AsyncSessionLocal() as db:
            request = QueryLogsRequest(nrql_query=nrql_query)

            response = await newrelic_logs_service.query_logs(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_query_logs_response(response)

    except Exception as e:
        logger.error(f"Error in query_newrelic_logs_tool: {e}")
        return f"Failed to query logs: {str(e)}"


@tool
async def search_newrelic_logs_tool(
    workspace_id: str,
    search_query: str,
    start_hours_ago: int = 1,
    limit: int = 100,
) -> str:
    """
    Search New Relic logs for a specific text term.

    Simplified search tool that looks for text matches in log messages.
    For complex queries, use query_newrelic_logs_tool instead.

    Use this tool to:
    - Find logs containing specific error messages or keywords
    - Search for request IDs, user IDs, or correlation IDs
    - Look for specific function names or API endpoints

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        search_query: Text to search for in log messages
        start_hours_ago: How many hours back to search (default: 1)
        limit: Maximum number of log entries to return (default: 100)

    Returns:
        Log entries containing the search term with timestamps

    Example usage:
        search_newrelic_logs_tool(
            workspace_id="<workspace-id>",
            search_query="ConnectionTimeout",
            start_hours_ago=2
        )
    """
    try:
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = FilterLogsRequest(
                query=search_query,
                startTime=int(start_time.timestamp() * 1000),
                endTime=int(end_time.timestamp() * 1000),
                limit=limit,
            )

            response = await newrelic_logs_service.filter_logs(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_logs_response(response, limit=limit)

    except Exception as e:
        logger.error(f"Error in search_newrelic_logs_tool: {e}")
        return f"Failed to search logs: {str(e)}"


# ============================================================================
# Metrics Tools
# ============================================================================


@tool
async def query_newrelic_metrics_tool(
    workspace_id: str,
    nrql_query: str,
) -> str:
    """
    Query New Relic metrics using NRQL (New Relic Query Language).

    Use this tool for advanced metric queries with aggregation and analysis.
    Essential for investigating performance issues, analyzing trends, and correlating metrics.

    Use this tool to:
    - Query application performance metrics (APM)
    - Analyze transaction durations and throughput
    - Track error rates and response times
    - Investigate custom metrics

    Common NRQL patterns:
    - Transaction duration: "SELECT average(duration) FROM Transaction SINCE 1 hour ago TIMESERIES"
    - Error rate: "SELECT percentage(count(*), WHERE error IS true) FROM Transaction SINCE 1 hour ago"
    - Throughput: "SELECT count(*) FROM Transaction SINCE 1 hour ago TIMESERIES FACET name"
    - Custom metrics: "SELECT average(newrelic.timeslice.value) FROM Metric WHERE metricTimesliceName = 'Custom/MyMetric' SINCE 1 hour ago"

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        nrql_query: NRQL query string for metrics

    Returns:
        Query results with metric data and metadata

    Example usage:
        query_newrelic_metrics_tool(
            workspace_id="<workspace-id>",
            nrql_query="SELECT average(duration) FROM Transaction WHERE appName = 'api-service' SINCE 30 minutes ago TIMESERIES"
        )
    """
    try:
        async with AsyncSessionLocal() as db:
            request = QueryMetricsRequest(nrql_query=nrql_query)

            response = await newrelic_metrics_service.query_metrics(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_metrics_response(response)

    except Exception as e:
        logger.error(f"Error in query_newrelic_metrics_tool: {e}")
        return f"Failed to query metrics: {str(e)}"


@tool
async def get_newrelic_time_series_tool(
    workspace_id: str,
    metric_name: str,
    start_hours_ago: int = 1,
    aggregation: str = "average",
    where_clause: Optional[str] = None,
) -> str:
    """
    Get New Relic metric time series data.

    Use this tool to fetch time-series metric data and analyze trends over time.
    Useful for investigating performance degradation, spikes, or anomalies.

    Use this tool to:
    - Monitor performance metrics over time
    - Track trends in response times, throughput, or error rates
    - Correlate metrics with incidents
    - Identify patterns and anomalies

    Common metrics:
    - duration: Transaction duration in seconds
    - databaseDuration: Database query duration
    - externalDuration: External service call duration
    - httpResponseTimeAverage: HTTP response time

    Aggregation options: average, sum, min, max, count

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        metric_name: Metric name (e.g., "duration", "databaseDuration")
        start_hours_ago: How many hours back to fetch data (default: 1)
        aggregation: Aggregation function - average, sum, min, max, count (default: "average")
        where_clause: Optional WHERE clause for filtering (e.g., "appName = 'api-service'")

    Returns:
        Metric time series with latest, average, maximum, minimum values and recent data points

    Example usage:
        get_newrelic_time_series_tool(
            workspace_id="<workspace-id>",
            metric_name="duration",
            start_hours_ago=2,
            aggregation="average",
            where_clause="appName = 'api-service' AND transactionType = 'Web'"
        )
    """
    try:
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = GetTimeSeriesRequest(
                metric_name=metric_name,
                startTime=int(start_time.timestamp()),
                endTime=int(end_time.timestamp()),
                aggregation=aggregation,
                timeseries=True,
                where_clause=where_clause,
            )

            response = await newrelic_metrics_service.get_time_series(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_time_series_response(response)

    except Exception as e:
        logger.error(f"Error in get_newrelic_time_series_tool: {e}")
        return f"Failed to get time series: {str(e)}"


@tool
async def get_newrelic_infra_metrics_tool(
    workspace_id: str,
    metric_name: str,
    start_hours_ago: int = 1,
    aggregation: str = "average",
    hostname: Optional[str] = None,
) -> str:
    """
    Get New Relic infrastructure metrics.

    Use this tool to fetch infrastructure monitoring data like CPU, memory, disk, and network.
    Essential for correlating application issues with infrastructure problems.

    Use this tool to:
    - Monitor server resource utilization (CPU, memory, disk)
    - Investigate infrastructure-related performance issues
    - Correlate infrastructure metrics with application errors
    - Track host-level metrics over time

    Common infrastructure metrics:
    - cpuPercent: CPU utilization percentage
    - memoryUsedPercent: Memory utilization percentage
    - diskUsedPercent: Disk utilization percentage
    - loadAverageOneMinute: System load average (1 minute)
    - networkReceiveBytesPerSecond: Network ingress
    - networkTransmitBytesPerSecond: Network egress

    Aggregation options: average, sum, min, max

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        metric_name: Infrastructure metric name (e.g., "cpuPercent", "memoryUsedPercent")
        start_hours_ago: How many hours back to fetch data (default: 1)
        aggregation: Aggregation function - average, sum, min, max (default: "average")
        hostname: Optional hostname to filter by specific host

    Returns:
        Infrastructure metric time series with statistics and recent data points

    Example usage:
        get_newrelic_infra_metrics_tool(
            workspace_id="<workspace-id>",
            metric_name="cpuPercent",
            start_hours_ago=2,
            hostname="web-server-01"
        )
    """
    try:
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = GetInfraMetricsRequest(
                metric_name=metric_name,
                hostname=hostname,
                startTime=int(start_time.timestamp()),
                endTime=int(end_time.timestamp()),
                aggregation=aggregation,
            )

            response = await newrelic_metrics_service.get_infra_metrics(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_time_series_response(response)

    except Exception as e:
        logger.error(f"Error in get_newrelic_infra_metrics_tool: {e}")
        return f"Failed to get infrastructure metrics: {str(e)}"


# Export all tools
__all__ = [
    "query_newrelic_logs_tool",
    "search_newrelic_logs_tool",
    "query_newrelic_metrics_tool",
    "get_newrelic_time_series_tool",
    "get_newrelic_infra_metrics_tool",
]
