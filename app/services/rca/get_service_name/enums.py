"""
Enums for RCA service
"""
from enum import Enum


class ToolFriendlyMessage(str, Enum):
    """User-friendly messages for RCA tool execution"""

    # Log tools
    FETCH_ERROR_LOGS = "🔍 Checking error logs..."
    FETCH_LOGS = "📜 Fetching logs..."

    # Metrics tools
    FETCH_CPU_METRICS = "📊 Analyzing CPU metrics..."
    FETCH_MEMORY_METRICS = "💾 Analyzing memory usage..."
    FETCH_HTTP_LATENCY = "⏱️ Checking HTTP latency..."
    FETCH_METRICS = "📈 Fetching metrics..."

    # Repository tools
    LIST_REPOSITORIES = "📦 Listing GitHub repositories..."
    LIST_ALL_SERVICES = "🔎 Discovering all services in workspace..."
    DISCOVER_SERVICE_NAME = "🏷️ Identifying service name from repository..."
    SCAN_REPOSITORY_FOR_SERVICES = "🔍 Scanning repository for service names..."
    READ_REPOSITORY_FILE = "📄 Reading code file..."
    SEARCH_CODE = "🔎 Searching codebase..."
    GET_REPOSITORY_COMMITS = "📝 Checking recent commits..."
    LIST_PULL_REQUESTS = "🔀 Reviewing pull requests..."
    DOWNLOAD_FILE = "⬇️ Downloading file..."
    GET_REPOSITORY_TREE = "🌳 Exploring repository structure..."
    GET_BRANCH_RECENT_COMMITS = "🌿 Checking branch commits..."
    GET_REPOSITORY_METADATA = "ℹ️ Fetching repository metadata..."


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
}
