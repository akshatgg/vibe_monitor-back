"""
Enums for RCA service
"""

from enum import Enum


class ToolFriendlyMessage(str, Enum):
    """User-friendly messages for RCA tool execution"""

    # Log tools
    FETCH_ERROR_LOGS = "Checking error logs..."
    FETCH_LOGS = "Fetching logs..."

    # Metrics tools
    FETCH_CPU_METRICS = "Analyzing CPU metrics..."
    FETCH_MEMORY_METRICS = "Analyzing memory usage..."
    FETCH_HTTP_LATENCY = "Checking HTTP latency..."
    FETCH_METRICS = "Fetching metrics..."

    # Repository tools
    LIST_REPOSITORIES = "Listing GitHub repositories..."
    LIST_ALL_SERVICES = "Discovering all services in workspace..."
    DISCOVER_SERVICE_NAME = "Identifying service name from repository..."
    SCAN_REPOSITORY_FOR_SERVICES = "Scanning repository for service names..."
    READ_REPOSITORY_FILE = "Reading code file..."
    SEARCH_CODE = "Searching codebase..."
    GET_REPOSITORY_COMMITS = "Checking recent commits..."
    LIST_PULL_REQUESTS = "Reviewing pull requests..."
    DOWNLOAD_FILE = "Downloading file..."
    GET_REPOSITORY_TREE = "Exploring repository structure..."
    GET_BRANCH_RECENT_COMMITS = "Checking branch commits..."
    GET_REPOSITORY_METADATA = "Fetching repository metadata..."

    # Grafana datasource tools
    GET_DATASOURCES = "Discovering datasources..."
    GET_LABELS = "Discovering available labels..."
    GET_LABEL_VALUES = "Fetching label values..."

    # CloudWatch tools
    LIST_CLOUDWATCH_LOG_GROUPS = "Listing CloudWatch log groups..."
    FILTER_CLOUDWATCH_LOG_EVENTS = "Filtering CloudWatch log events..."
    SEARCH_CLOUDWATCH_LOGS = "Searching CloudWatch logs..."
    EXECUTE_CLOUDWATCH_INSIGHTS_QUERY = "Running CloudWatch Insights query..."
    LIST_CLOUDWATCH_METRICS = "Listing CloudWatch metrics..."
    GET_CLOUDWATCH_METRIC_STATISTICS = "Fetching CloudWatch metric statistics..."
    LIST_CLOUDWATCH_NAMESPACES = "Listing CloudWatch namespaces..."

    # Datadog tools
    SEARCH_DATADOG_LOGS = "Searching Datadog logs..."
    LIST_DATADOG_LOGS = "Listing Datadog logs..."
    LIST_DATADOG_LOG_SERVICES = "Listing Datadog log services..."
    QUERY_DATADOG_METRICS = "Querying Datadog metrics..."
    QUERY_DATADOG_TIMESERIES = "Fetching Datadog time series..."
    SEARCH_DATADOG_EVENTS = "Searching Datadog events..."
    LIST_DATADOG_TAGS = "Listing Datadog tags..."

    # New Relic tools
    QUERY_NEWRELIC_LOGS = "Querying New Relic logs..."
    SEARCH_NEWRELIC_LOGS = "Searching New Relic logs..."
    QUERY_NEWRELIC_METRICS = "Querying New Relic metrics..."
    GET_NEWRELIC_TIME_SERIES = "Fetching New Relic time series..."
    GET_NEWRELIC_INFRA_METRICS = "Fetching New Relic infrastructure metrics..."


# Mapping from tool names to enum values
TOOL_NAME_TO_MESSAGE = {
    "fetch_error_logs_tool": ToolFriendlyMessage.FETCH_ERROR_LOGS,
    "fetch_logs_tool": ToolFriendlyMessage.FETCH_LOGS,
    "fetch_cpu_metrics_tool": ToolFriendlyMessage.FETCH_CPU_METRICS,
    "fetch_memory_metrics_tool": ToolFriendlyMessage.FETCH_MEMORY_METRICS,
    "fetch_http_latency_tool": ToolFriendlyMessage.FETCH_HTTP_LATENCY,
    "fetch_metrics_tool": ToolFriendlyMessage.FETCH_METRICS,
    "list_repositories_tool": ToolFriendlyMessage.LIST_REPOSITORIES,
    "list_all_services_tool": ToolFriendlyMessage.LIST_ALL_SERVICES,
    "discover_service_name_tool": ToolFriendlyMessage.DISCOVER_SERVICE_NAME,
    "scan_repository_for_services_tool": ToolFriendlyMessage.SCAN_REPOSITORY_FOR_SERVICES,
    "read_repository_file_tool": ToolFriendlyMessage.READ_REPOSITORY_FILE,
    "search_code_tool": ToolFriendlyMessage.SEARCH_CODE,
    "get_repository_commits_tool": ToolFriendlyMessage.GET_REPOSITORY_COMMITS,
    "list_pull_requests_tool": ToolFriendlyMessage.LIST_PULL_REQUESTS,
    "download_file_tool": ToolFriendlyMessage.DOWNLOAD_FILE,
    "get_repository_tree_tool": ToolFriendlyMessage.GET_REPOSITORY_TREE,
    "get_branch_recent_commits_tool": ToolFriendlyMessage.GET_BRANCH_RECENT_COMMITS,
    "get_repository_metadata_tool": ToolFriendlyMessage.GET_REPOSITORY_METADATA,
    # Grafana datasource tools
    "get_datasources_tool": ToolFriendlyMessage.GET_DATASOURCES,
    "get_labels_tool": ToolFriendlyMessage.GET_LABELS,
    "get_label_values_tool": ToolFriendlyMessage.GET_LABEL_VALUES,
    # CloudWatch tools
    "list_cloudwatch_log_groups_tool": ToolFriendlyMessage.LIST_CLOUDWATCH_LOG_GROUPS,
    "filter_cloudwatch_log_events_tool": ToolFriendlyMessage.FILTER_CLOUDWATCH_LOG_EVENTS,
    "search_cloudwatch_logs_tool": ToolFriendlyMessage.SEARCH_CLOUDWATCH_LOGS,
    "execute_cloudwatch_insights_query_tool": ToolFriendlyMessage.EXECUTE_CLOUDWATCH_INSIGHTS_QUERY,
    "list_cloudwatch_metrics_tool": ToolFriendlyMessage.LIST_CLOUDWATCH_METRICS,
    "get_cloudwatch_metric_statistics_tool": ToolFriendlyMessage.GET_CLOUDWATCH_METRIC_STATISTICS,
    "list_cloudwatch_namespaces_tool": ToolFriendlyMessage.LIST_CLOUDWATCH_NAMESPACES,
    # Datadog tools
    "search_datadog_logs_tool": ToolFriendlyMessage.SEARCH_DATADOG_LOGS,
    "list_datadog_logs_tool": ToolFriendlyMessage.LIST_DATADOG_LOGS,
    "list_datadog_log_services_tool": ToolFriendlyMessage.LIST_DATADOG_LOG_SERVICES,
    "query_datadog_metrics_tool": ToolFriendlyMessage.QUERY_DATADOG_METRICS,
    "query_datadog_timeseries_tool": ToolFriendlyMessage.QUERY_DATADOG_TIMESERIES,
    "search_datadog_events_tool": ToolFriendlyMessage.SEARCH_DATADOG_EVENTS,
    "list_datadog_tags_tool": ToolFriendlyMessage.LIST_DATADOG_TAGS,
    # New Relic tools
    "query_newrelic_logs_tool": ToolFriendlyMessage.QUERY_NEWRELIC_LOGS,
    "search_newrelic_logs_tool": ToolFriendlyMessage.SEARCH_NEWRELIC_LOGS,
    "query_newrelic_metrics_tool": ToolFriendlyMessage.QUERY_NEWRELIC_METRICS,
    "get_newrelic_time_series_tool": ToolFriendlyMessage.GET_NEWRELIC_TIME_SERIES,
    "get_newrelic_infra_metrics_tool": ToolFriendlyMessage.GET_NEWRELIC_INFRA_METRICS,
}
