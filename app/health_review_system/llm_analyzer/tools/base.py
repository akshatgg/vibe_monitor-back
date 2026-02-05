"""
Base utilities for LLM Analyzer tools.

Provides context management and tool registration.
"""

import contextvars
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.health_review_system.codebase_sync.schemas import ParsedCodebaseInfo, ParsedFileInfo
from app.health_review_system.data_collector.schemas import CollectedData, LogEntry, ErrorData

logger = logging.getLogger(__name__)

# Context variable for passing data to tools
_analysis_context: contextvars.ContextVar[Optional["AnalysisContext"]] = contextvars.ContextVar(
    "analysis_context", default=None
)


@dataclass
class AnalysisContext:
    """
    Context object passed to all analysis tools.

    Contains the parsed codebase and collected observability data
    that tools use to perform analysis.
    """

    # Codebase information
    codebase: Optional[ParsedCodebaseInfo] = None

    # Collected observability data
    collected_data: Optional[CollectedData] = None

    # Service metadata
    service_name: str = ""
    repository_name: str = ""

    # File content cache (file_path -> content)
    _file_content_cache: Dict[str, str] = field(default_factory=dict)

    def get_file(self, file_path: str) -> Optional[ParsedFileInfo]:
        """Get a parsed file by path."""
        if not self.codebase or not self.codebase.files:
            return None

        for f in self.codebase.files:
            if f.path == file_path:
                return f
        return None

    def get_file_content(self, file_path: str) -> Optional[str]:
        """
        Get file content by path.

        Note: Content may not be available if not stored during parsing.
        """
        # Check cache first
        if file_path in self._file_content_cache:
            return self._file_content_cache[file_path]

        # Content is not stored in ParsedFileInfo currently
        # This would need to be fetched from the database if needed
        return None

    def get_all_functions(self) -> List[Dict[str, Any]]:
        """Get all functions across all files."""
        if not self.codebase or not self.codebase.files:
            return []

        functions = []
        for f in self.codebase.files:
            for func_name in f.functions:
                functions.append({
                    "name": func_name,
                    "file": f.path,
                })
        return functions

    def get_all_classes(self) -> List[Dict[str, Any]]:
        """Get all classes across all files."""
        if not self.codebase or not self.codebase.files:
            return []

        classes = []
        for f in self.codebase.files:
            for class_name in f.classes:
                classes.append({
                    "name": class_name,
                    "file": f.path,
                })
        return classes

    def get_logs(self, level: Optional[str] = None, limit: int = 100) -> List[LogEntry]:
        """Get logs, optionally filtered by level."""
        if not self.collected_data or not self.collected_data.logs:
            return []

        logs = self.collected_data.logs

        if level:
            level_lower = level.lower()
            logs = [log for log in logs if log.level.lower() == level_lower]

        return logs[:limit]

    def get_errors(self) -> List[ErrorData]:
        """Get aggregated error data."""
        if not self.collected_data or not self.collected_data.errors:
            return []
        return self.collected_data.errors

    def get_metrics(self) -> Dict[str, Any]:
        """Get metrics data as dict."""
        if not self.collected_data or not self.collected_data.metrics:
            return {}
        return self.collected_data.metrics.model_dump()


def set_analysis_context(context: AnalysisContext) -> contextvars.Token:
    """
    Set the analysis context for the current execution.

    Returns a token that can be used to reset the context.
    """
    return _analysis_context.set(context)


def get_analysis_context() -> AnalysisContext:
    """
    Get the current analysis context.

    Raises ValueError if no context is set.
    """
    context = _analysis_context.get()
    if context is None:
        raise ValueError(
            "No analysis context set. Call set_analysis_context() before using tools."
        )
    return context


def reset_analysis_context(token: contextvars.Token) -> None:
    """Reset the analysis context using a token."""
    _analysis_context.reset(token)


def get_all_tools() -> List:
    """
    Get all available tools for the ReAct agent.

    Returns a list of LangChain tool objects.
    """
    from app.health_review_system.llm_analyzer.tools.code_tools import (
        read_file,
        search_files,
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

    return [
        # Code tools
        read_file,
        search_files,
        search_functions,
        search_classes,
        get_function_details,
        list_files,
        # Log tools
        search_logs,
        get_error_patterns,
        check_error_logged,
        get_log_stats,
        # Metrics tools
        get_current_metrics,
        get_metrics_summary,
    ]
