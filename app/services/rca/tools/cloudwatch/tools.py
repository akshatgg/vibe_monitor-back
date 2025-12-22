"""
LangChain tools for RCA agent to interact with AWS CloudWatch Logs and Metrics
"""

import logging
from typing import Optional
from datetime import datetime, timedelta, timezone
from langchain.tools import tool

from app.aws.cloudwatch.Logs.service import cloudwatch_logs_service
from app.aws.cloudwatch.Logs.schemas import (
    ListLogGroupsRequest,
    FilterLogEventsRequest,
    StartQueryRequest,
)
from app.aws.cloudwatch.Metrics.service import cloudwatch_metrics_service
from app.aws.cloudwatch.Metrics.schemas import (
    ListMetricsRequest,
    GetMetricStatisticsRequest,
    Dimension,
)
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


# ============================================================================
# Response Formatters
# ============================================================================


def _format_log_groups_response(response) -> str:
    """Format CloudWatch log groups response for LLM consumption"""
    try:
        if not response.logGroups:
            return "No log groups found for this workspace."

        formatted = []
        for log_group in response.logGroups[:30]:  # Limit to first 30
            log_group_name = log_group.logGroupName
            retention = (
                log_group.retentionInDays
                if log_group.retentionInDays
                else "Never expires"
            )
            stored_bytes = log_group.storedBytes

            formatted.append(
                f"📦 **{log_group_name}**\n"
                f"   Size: {stored_bytes:,} bytes\n"
                f"   Retention: {retention}\n"
                f"   Class: {log_group.logGroupClass}"
            )

        summary = f"Found {response.totalCount} log groups:\n\n" + "\n\n".join(
            formatted
        )

        if response.totalCount > 30:
            summary += (
                f"\n\n(Showing first 30 log groups. Total: {response.totalCount})"
            )

        return summary

    except Exception as e:
        logger.error(f"Error formatting log groups response: {e}")
        return f"Error parsing log groups: {str(e)}"


def _format_log_events_response(response, limit: int = 50) -> str:
    """Format CloudWatch log events response for LLM consumption"""
    try:
        if not response.events:
            return "No log events found for the specified criteria."

        logs = []
        for event in response.events[:limit]:
            # Convert timestamp from milliseconds to datetime
            timestamp = datetime.fromtimestamp(event.timestamp / 1000, tz=timezone.utc)
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
            message = event.message.strip()

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
        logger.error(f"Error formatting log events: {e}")
        return f"Error parsing log events: {str(e)}"


def _format_insights_query_response(response) -> str:
    """Format CloudWatch Insights query results for LLM consumption"""
    try:
        if response.status != "Complete":
            return f"Query status: {response.status}"

        if not response.results:
            return "Query completed but no results found."

        # Format results as table
        formatted_rows = []
        for row in response.results[:50]:  # Limit to first 50 results
            fields = {}
            for field in row:
                fields[field.field] = field.value or ""

            # Create a formatted row
            row_str = " | ".join([f"{k}: {v}" for k, v in fields.items()])
            formatted_rows.append(row_str)

        summary = (
            f"Query completed successfully. Found {len(response.results)} results:\n\n"
        )
        summary += "\n".join(formatted_rows)

        if response.statistics:
            summary += "\n\n📊 **Statistics:**\n"
            summary += f"   Records matched: {response.statistics.recordsMatched}\n"
            summary += f"   Records scanned: {response.statistics.recordsScanned}\n"
            summary += f"   Bytes scanned: {response.statistics.bytesScanned}"

        if len(response.results) > 50:
            summary += f"\n\n(Showing first 50 results. Total: {len(response.results)})"

        return summary

    except Exception as e:
        logger.error(f"Error formatting insights query: {e}")
        return f"Error parsing query results: {str(e)}"


def _format_metrics_response(response) -> str:
    """Format CloudWatch metrics list response for LLM consumption"""
    try:
        if not response.Metrics:
            return "No metrics found for the specified criteria."

        formatted = []
        for metric in response.Metrics[:30]:  # Limit to first 30
            namespace = metric.Namespace or "Unknown"
            metric_name = metric.MetricName or "Unknown"

            dimensions_str = ""
            if metric.Dimensions:
                dims = [f"{d.get('Name')}={d.get('Value')}" for d in metric.Dimensions]
                dimensions_str = f"\n   Dimensions: {', '.join(dims)}"

            formatted.append(
                f"📊 **{metric_name}**\n   Namespace: {namespace}{dimensions_str}"
            )

        summary = f"Found {response.TotalCount} metrics:\n\n" + "\n\n".join(formatted)

        if response.TotalCount > 30:
            summary += f"\n\n(Showing first 30 metrics. Total: {response.TotalCount})"

        return summary

    except Exception as e:
        logger.error(f"Error formatting metrics response: {e}")
        return f"Error parsing metrics: {str(e)}"


def _format_metric_statistics_response(response, metric_name: str) -> str:
    """Format CloudWatch metric statistics response for LLM consumption"""
    try:
        if not response.Datapoints:
            return f"No data points found for metric '{metric_name}'."

        # Calculate statistics from datapoints
        values = []
        for dp in response.Datapoints:
            if dp.Average is not None:
                values.append(dp.Average)
            elif dp.Sum is not None:
                values.append(dp.Sum)

        if not values:
            return f"No valid data points found for metric '{metric_name}'."

        latest = values[-1] if values else 0
        avg = sum(values) / len(values) if values else 0
        max_val = max(values) if values else 0
        min_val = min(values) if values else 0

        # Format timestamps for first and last datapoint
        first_time = response.Datapoints[0].Timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        last_time = response.Datapoints[-1].Timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        formatted = (
            f"📊 Metrics for **{metric_name}** (from {first_time} to {last_time}):\n\n"
            f"  Latest: {latest:.2f}\n"
            f"  Average: {avg:.2f}\n"
            f"  Maximum: {max_val:.2f}\n"
            f"  Minimum: {min_val:.2f}\n"
            f"  Data points: {len(values)}\n"
        )

        # Add individual datapoints for detailed analysis
        formatted += "\nRecent data points:\n"
        for dp in response.Datapoints[-10:]:  # Last 10 datapoints
            ts = dp.Timestamp.strftime("%H:%M:%S")
            val = dp.Average if dp.Average is not None else dp.Sum
            formatted += f"  {ts}: {val:.2f}\n"

        return formatted

    except Exception as e:
        logger.error(f"Error formatting metric statistics: {e}")
        return f"Error parsing metric statistics: {str(e)}"


def _format_namespaces_response(response) -> str:
    """Format CloudWatch namespaces response for LLM consumption"""
    try:
        if not response.Namespaces:
            return "No namespaces found."

        formatted = []
        for namespace in response.Namespaces:
            formatted.append(f"  • {namespace}")

        summary = f"Found {len(response.Namespaces)} namespaces:\n\n" + "\n".join(
            formatted
        )
        return summary

    except Exception as e:
        logger.error(f"Error formatting namespaces response: {e}")
        return f"Error parsing namespaces: {str(e)}"


# ============================================================================
# Log Tools
# ============================================================================


@tool
async def list_cloudwatch_log_groups_tool(
    workspace_id: str,
    name_prefix: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    List CloudWatch log groups in the workspace.

    Use this tool to discover available log groups before querying logs.
    Essential for understanding what services are logging to CloudWatch.

    Use this tool to:
    - Discover all log groups in the AWS account
    - Find log groups for specific services or applications
    - Understand data retention and storage for logs

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        name_prefix: Optional prefix to filter log groups (e.g., "/aws/lambda/", "/ecs/")
        limit: Maximum number of log groups to return (default: 50, max: 100)

    Returns:
        Formatted list of log groups with sizes, retention periods, and classes

    Example usage:
        list_cloudwatch_log_groups_tool(
            workspace_id="<workspace-id>",
            name_prefix="/aws/lambda/"
        )
    """
    try:
        async with AsyncSessionLocal() as db:
            request = ListLogGroupsRequest(
                logGroupNamePrefix=name_prefix, limit=min(limit, 100)
            )

            response = await cloudwatch_logs_service.list_log_groups(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_log_groups_response(response)

    except Exception as e:
        logger.error(f"Error in list_cloudwatch_log_groups_tool: {e}")
        return f"Failed to list log groups: {str(e)}"


@tool
async def filter_cloudwatch_log_events_tool(
    workspace_id: str,
    log_group_name: str,
    filter_pattern: Optional[str] = None,
    start_hours_ago: int = 1,
    limit: int = 100,
) -> str:
    """
    Filter and search log events across CloudWatch log streams.

    Use this tool to search for specific patterns, errors, or keywords in logs.
    Searches across all log streams in a log group.

    Use this tool to:
    - Search for specific error messages or patterns
    - Find logs containing specific keywords (e.g., "timeout", "failed", "error")
    - Investigate issues by searching for request IDs or correlation IDs
    - Filter logs by CloudWatch filter patterns

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        log_group_name: CloudWatch log group name (get from list_cloudwatch_log_groups_tool)
        filter_pattern: CloudWatch filter pattern (e.g., "ERROR", "[ERROR]", "timeout")
        start_hours_ago: How many hours back to search (default: 1)
        limit: Maximum number of log entries to return (default: 100, max: 1000)

    Returns:
        Log events matching the filter pattern with timestamps and messages

    Example usage:
        filter_cloudwatch_log_events_tool(
            workspace_id="<workspace-id>",
            log_group_name="/aws/lambda/my-function",
            filter_pattern="ERROR",
            start_hours_ago=2
        )
    """
    try:
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = FilterLogEventsRequest(
                logGroupName=log_group_name,
                filterPattern=filter_pattern,
                startTime=int(start_time.timestamp() * 1000),
                endTime=int(end_time.timestamp() * 1000),
                limit=min(limit, 1000),
            )

            response = await cloudwatch_logs_service.filter_log_events(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_log_events_response(response, limit=limit)

    except Exception as e:
        logger.error(f"Error in filter_cloudwatch_log_events_tool: {e}")
        return f"Failed to filter log events: {str(e)}"


@tool
async def search_cloudwatch_logs_tool(
    workspace_id: str,
    log_group_name: str,
    search_term: str,
    start_hours_ago: int = 1,
    limit: int = 100,
) -> str:
    """
    Search CloudWatch logs for a specific text term.

    Simplified search tool that looks for exact text matches in log messages.
    For complex patterns, use filter_cloudwatch_log_events_tool instead.

    Use this tool to:
    - Find logs containing specific text or error messages
    - Search for request IDs, user IDs, or transaction IDs
    - Look for specific function names or API endpoints

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        log_group_name: CloudWatch log group name
        search_term: Text to search for in log messages
        start_hours_ago: How many hours back to search (default: 1)
        limit: Maximum number of log entries to return (default: 100)

    Returns:
        Log events containing the search term with timestamps

    Example usage:
        search_cloudwatch_logs_tool(
            workspace_id="<workspace-id>",
            log_group_name="/aws/lambda/my-function",
            search_term="ConnectionTimeout",
            start_hours_ago=2
        )
    """
    try:
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = FilterLogEventsRequest(
                logGroupName=log_group_name,
                filterPattern=f'"{search_term}"',  # CloudWatch exact match pattern
                startTime=int(start_time.timestamp() * 1000),
                endTime=int(end_time.timestamp() * 1000),
                limit=min(limit, 1000),
            )

            response = await cloudwatch_logs_service.filter_log_events(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_log_events_response(response, limit=limit)

    except Exception as e:
        logger.error(f"Error in search_cloudwatch_logs_tool: {e}")
        return f"Failed to search logs: {str(e)}"


@tool
async def execute_cloudwatch_insights_query_tool(
    workspace_id: str,
    log_group_name: str,
    query_string: str,
    start_hours_ago: int = 1,
    limit: int = 100,
    max_wait_seconds: int = 60,
) -> str:
    """
    Execute a CloudWatch Logs Insights query for advanced log analysis.

    CloudWatch Logs Insights is a powerful query language for searching and analyzing logs.
    Use this for complex queries that require aggregation, filtering, or statistics.

    Use this tool to:
    - Analyze log patterns and trends
    - Aggregate error counts or response times
    - Extract specific fields from structured logs (JSON)
    - Calculate statistics over time periods

    Common query patterns:
    - Count errors: "fields @timestamp, @message | filter @message like /ERROR/ | stats count() by bin(5m)"
    - Parse JSON: "fields @timestamp, @message | parse @message /(?<level>[A-Z]+):/ | filter level = 'ERROR'"
    - Top errors: "filter @message like /ERROR/ | stats count() as error_count by @message | sort error_count desc"

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        log_group_name: CloudWatch log group name
        query_string: CloudWatch Insights query string
        start_hours_ago: How many hours back to query (default: 1)
        limit: Maximum number of results (default: 100, max: 10000)
        max_wait_seconds: Maximum time to wait for query results (default: 60)

    Returns:
        Query results with statistics and matched records

    Example usage:
        execute_cloudwatch_insights_query_tool(
            workspace_id="<workspace-id>",
            log_group_name="/aws/lambda/my-function",
            query_string="fields @timestamp, @message | filter @message like /ERROR/ | limit 50"
        )
    """
    try:
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        async with AsyncSessionLocal() as db:
            request = StartQueryRequest(
                logGroupName=log_group_name,
                queryString=query_string,
                startTime=int(start_time.timestamp()),
                endTime=int(end_time.timestamp()),
                limit=min(limit, 10000),
            )

            response = await cloudwatch_logs_service.execute_query(
                db=db,
                workspace_id=workspace_id,
                request=request,
                max_wait_seconds=max_wait_seconds,
            )

        return _format_insights_query_response(response)

    except Exception as e:
        logger.error(f"Error in execute_cloudwatch_insights_query_tool: {e}")
        return f"Failed to execute query: {str(e)}"


# ============================================================================
# Metrics Tools
# ============================================================================


@tool
async def list_cloudwatch_metrics_tool(
    workspace_id: str,
    namespace: Optional[str] = None,
    metric_name: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    List available CloudWatch metrics.

    Use this tool to discover what metrics are available for monitoring and analysis.
    Metrics are organized by namespace (AWS service or custom application).

    Use this tool to:
    - Discover available metrics in an AWS account
    - Find metrics for specific services (EC2, Lambda, RDS, etc.)
    - Understand metric dimensions (instance IDs, function names, etc.)

    Common namespaces:
    - AWS/EC2: EC2 instance metrics (CPUUtilization, NetworkIn, DiskWriteOps)
    - AWS/Lambda: Lambda function metrics (Invocations, Errors, Duration, Throttles)
    - AWS/RDS: RDS database metrics (DatabaseConnections, CPUUtilization, ReadLatency)
    - AWS/ECS: ECS service metrics (CPUUtilization, MemoryUtilization)
    - AWS/ApplicationELB: Application Load Balancer metrics (RequestCount, TargetResponseTime)

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        namespace: Optional namespace filter (e.g., "AWS/Lambda", "AWS/EC2")
        metric_name: Optional metric name filter (e.g., "CPUUtilization")
        limit: Maximum number of metrics to return (default: 50)

    Returns:
        List of metrics with namespaces and dimensions

    Example usage:
        list_cloudwatch_metrics_tool(
            workspace_id="<workspace-id>",
            namespace="AWS/Lambda"
        )
    """
    try:
        async with AsyncSessionLocal() as db:
            request = ListMetricsRequest(
                Namespace=namespace, MetricName=metric_name, Limit=limit
            )

            response = await cloudwatch_metrics_service.list_metrics(
                db=db, workspace_id=workspace_id, request=request
            )

        return _format_metrics_response(response)

    except Exception as e:
        logger.error(f"Error in list_cloudwatch_metrics_tool: {e}")
        return f"Failed to list metrics: {str(e)}"


@tool
async def get_cloudwatch_metric_statistics_tool(
    workspace_id: str,
    namespace: str,
    metric_name: str,
    statistic: str = "Average",
    start_hours_ago: int = 1,
    period_seconds: int = 300,
    dimension_name: Optional[str] = None,
    dimension_value: Optional[str] = None,
) -> str:
    """
    Get CloudWatch metric statistics for performance analysis.

    Use this tool to fetch time-series data for metrics and analyze trends.
    Essential for investigating performance issues, resource utilization, and errors.

    Use this tool to:
    - Monitor CPU, memory, or disk utilization
    - Track error rates and request counts
    - Analyze response times and latencies
    - Correlate metrics with incidents

    Common metrics by service:
    - EC2: CPUUtilization, NetworkIn, NetworkOut, DiskReadOps, DiskWriteOps
    - Lambda: Invocations, Errors, Duration, Throttles, ConcurrentExecutions
    - RDS: CPUUtilization, DatabaseConnections, ReadLatency, WriteLatency
    - ECS: CPUUtilization, MemoryUtilization
    - ALB: RequestCount, TargetResponseTime, HTTPCode_Target_4XX_Count

    Statistics available: Average, Sum, Minimum, Maximum, SampleCount

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)
        namespace: CloudWatch namespace (e.g., "AWS/Lambda", "AWS/EC2")
        metric_name: Metric name (e.g., "CPUUtilization", "Errors", "Duration")
        statistic: Statistic to fetch - Average, Sum, Minimum, Maximum (default: "Average")
        start_hours_ago: How many hours back to fetch data (default: 1)
        period_seconds: Period in seconds for data points (default: 300 = 5 minutes)
        dimension_name: Optional dimension name (e.g., "FunctionName", "InstanceId")
        dimension_value: Optional dimension value (e.g., "my-function", "i-1234567")

    Returns:
        Metric statistics with latest, average, maximum, minimum values and recent data points

    Example usage:
        get_cloudwatch_metric_statistics_tool(
            workspace_id="<workspace-id>",
            namespace="AWS/Lambda",
            metric_name="Errors",
            statistic="Sum",
            dimension_name="FunctionName",
            dimension_value="my-function",
            start_hours_ago=2
        )
    """
    try:
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=start_hours_ago)

        # Build dimensions list
        dimensions = []
        if dimension_name and dimension_value:
            dimensions.append(Dimension(Name=dimension_name, Value=dimension_value))

        async with AsyncSessionLocal() as db:
            request = GetMetricStatisticsRequest(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions if dimensions else None,
                StartTime=int(start_time.timestamp()),
                EndTime=int(end_time.timestamp()),
                Period=period_seconds,
                Statistics=[statistic],
                MaxDatapoints=50,
            )

            response = await cloudwatch_metrics_service.get_metric_statistics(
                db=db, workspace_id=workspace_id, request=request
            )

        metric_label = f"{namespace}/{metric_name}"
        if dimension_name and dimension_value:
            metric_label += f" ({dimension_name}={dimension_value})"

        return _format_metric_statistics_response(response, metric_label)

    except Exception as e:
        logger.error(f"Error in get_cloudwatch_metric_statistics_tool: {e}")
        return f"Failed to get metric statistics: {str(e)}"


@tool
async def list_cloudwatch_namespaces_tool(
    workspace_id: str,
) -> str:
    """
    List all unique CloudWatch metric namespaces available in the account.

    Use this tool to discover what AWS services and custom applications
    are publishing metrics to CloudWatch.

    Use this tool to:
    - Discover all services publishing metrics
    - Find custom application namespaces
    - Understand the monitoring landscape

    Args:
        workspace_id: Workspace identifier (automatically provided from job context)

    Returns:
        List of unique namespaces

    Example usage:
        list_cloudwatch_namespaces_tool(workspace_id="<workspace-id>")
    """
    try:
        async with AsyncSessionLocal() as db:
            response = await cloudwatch_metrics_service.list_namespaces(
                db=db, workspace_id=workspace_id
            )

        return _format_namespaces_response(response)

    except Exception as e:
        logger.error(f"Error in list_cloudwatch_namespaces_tool: {e}")
        return f"Failed to list namespaces: {str(e)}"


# Export all tools
__all__ = [
    "list_cloudwatch_log_groups_tool",
    "filter_cloudwatch_log_events_tool",
    "search_cloudwatch_logs_tool",
    "execute_cloudwatch_insights_query_tool",
    "list_cloudwatch_metrics_tool",
    "get_cloudwatch_metric_statistics_tool",
    "list_cloudwatch_namespaces_tool",
]
