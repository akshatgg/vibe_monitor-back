"""
LLM Analyzer Tools Package.

Provides tools for the ReAct agent to analyze code, logs, and metrics.
"""

from app.health_review_system.llm_analyzer.tools.base import (
    AnalysisContext,
    get_all_tools,
    set_analysis_context,
    get_analysis_context,
)
from app.health_review_system.llm_analyzer.tools.code_tools import (
    read_file,
    search_functions,
    search_classes,
    get_function_details,
    list_files,
)
from app.health_review_system.llm_analyzer.tools.log_tools import (
    search_logs,
    get_error_patterns,
    check_error_logged,
    get_log_stats,
)
from app.health_review_system.llm_analyzer.tools.metrics_tools import (
    get_current_metrics,
    get_metrics_summary,
)

__all__ = [
    # Context
    "AnalysisContext",
    "get_all_tools",
    "set_analysis_context",
    "get_analysis_context",
    # Code tools
    "read_file",
    "search_functions",
    "search_classes",
    "get_function_details",
    "list_files",
    # Log tools
    "search_logs",
    "get_error_patterns",
    "check_error_logged",
    "get_log_stats",
    # Metrics tools
    "get_current_metrics",
    "get_metrics_summary",
]
