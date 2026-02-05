"""
Log Analysis Tools for LLM Analyzer.

Tools for searching and analyzing collected logs and errors.
"""

import json
import logging
import re
from typing import Optional

from langchain_core.tools import tool

from app.health_review_system.llm_analyzer.tools.base import get_analysis_context

logger = logging.getLogger(__name__)


@tool
def search_logs(query: str, level: Optional[str] = None, limit: int = 20) -> str:
    """
    Search logs by message content or pattern.

    Use this to find log entries related to specific functionality or errors.

    Args:
        query: Search string or regex pattern to match in log messages
        level: Optional filter by log level (e.g., "error", "warning", "info")
        limit: Maximum number of logs to return (default 20)

    Returns:
        JSON list of matching log entries with timestamps and levels.
    """
    try:
        context = get_analysis_context()

        if not context.collected_data or not context.collected_data.logs:
            return "No log data available."

        logs = context.collected_data.logs
        query_lower = query.lower()

        # Filter by level if specified
        if level:
            level_lower = level.lower()
            logs = [log for log in logs if log.level.lower() == level_lower]

        # Search in messages
        matching = []
        try:
            pattern = re.compile(query, re.IGNORECASE)
            use_regex = True
        except re.error:
            use_regex = False

        for log in logs:
            message = log.message or ""
            if use_regex:
                if pattern.search(message):
                    matching.append(log)
            else:
                if query_lower in message.lower():
                    matching.append(log)

            if len(matching) >= limit:
                break

        if not matching:
            return f"No logs found matching '{query}'" + (f" with level '{level}'" if level else "")

        results = []
        for log in matching:
            # Convert datetime to ISO string for JSON serialization
            timestamp_str = log.timestamp.isoformat() if hasattr(log.timestamp, 'isoformat') else str(log.timestamp)
            results.append({
                "timestamp": timestamp_str,
                "level": log.level,
                "message": log.message[:500] if log.message else "",  # Truncate long messages
                "service": log.service,
            })

        return json.dumps({
            "total_matching": len(matching),
            "shown": len(results),
            "logs": results,
        }, indent=2)

    except Exception as e:
        logger.exception(f"Error in search_logs: {e}")
        return f"Error searching logs: {str(e)}"


@tool
def get_error_patterns() -> str:
    """
    Get aggregated error patterns with occurrence counts.

    Use this to understand what types of errors are occurring and their frequency.
    This is essential for prioritizing which errors to investigate.

    Returns:
        JSON list of error patterns sorted by occurrence count.
    """
    try:
        context = get_analysis_context()

        if not context.collected_data or not context.collected_data.errors:
            return "No error data available. The service may not have any errors in the review period."

        errors = context.collected_data.errors

        results = []
        for error in errors:
            # Convert datetime to ISO string for JSON serialization
            first_seen_str = error.first_seen.isoformat() if hasattr(error.first_seen, 'isoformat') else str(error.first_seen)
            last_seen_str = error.last_seen.isoformat() if hasattr(error.last_seen, 'isoformat') else str(error.last_seen)
            results.append({
                "error_type": error.error_type,
                "count": error.count,
                "fingerprint": error.fingerprint,
                "message_sample": error.message_sample[:300] if error.message_sample else None,
                "first_seen": first_seen_str,
                "last_seen": last_seen_str,
            })

        # Sort by count descending
        results.sort(key=lambda x: x["count"], reverse=True)

        return json.dumps({
            "total_error_types": len(results),
            "errors": results,
        }, indent=2)

    except Exception as e:
        logger.exception(f"Error in get_error_patterns: {e}")
        return f"Error getting error patterns: {str(e)}"


@tool
def check_error_logged(error_type: str) -> str:
    """
    Check if a specific error type appears in the logs.

    Use this to verify if errors are being properly logged.
    If an error type exists in code but not in logs, it might indicate a logging gap.

    Args:
        error_type: The error type or exception name to check for

    Returns:
        Information about whether and how often this error appears in logs.
    """
    try:
        context = get_analysis_context()

        if not context.collected_data:
            return "No collected data available."

        error_type_lower = error_type.lower()

        # Check in aggregated errors
        error_count = 0
        if context.collected_data.errors:
            for error in context.collected_data.errors:
                if error_type_lower in error.error_type.lower():
                    error_count += error.count

        # Check in raw logs for mentions
        log_mentions = 0
        if context.collected_data.logs:
            for log in context.collected_data.logs:
                if log.message and error_type_lower in log.message.lower():
                    log_mentions += 1

        if error_count == 0 and log_mentions == 0:
            return json.dumps({
                "error_type": error_type,
                "found": False,
                "aggregated_error_count": 0,
                "log_mentions": 0,
                "gap_detected": False,
                "message": f"No occurrences of '{error_type}' found in logs or errors.",
            }, indent=2)

        # Detect silent failure pattern
        gap_detected = error_count > 0 and log_mentions == 0

        if gap_detected:
            message = f"SILENT FAILURE DETECTED: Aggregated error count for {error_type} is {error_count} but log mentions are {log_mentions}, indicating errors are occurring but not being logged."
        elif error_count > log_mentions * 10:
            message = f"POTENTIAL GAP: {error_type} has {error_count} error occurrences but only {log_mentions} log mentions - many errors may not be logged."
        else:
            message = f"'{error_type}' appears to be logged adequately ({log_mentions} log mentions for {error_count} errors)."

        return json.dumps({
            "error_type": error_type,
            "found": True,
            "aggregated_error_count": error_count,
            "log_mentions": log_mentions,
            "gap_detected": gap_detected,
            "message": message,
        }, indent=2)

    except Exception as e:
        logger.exception(f"Error in check_error_logged: {e}")
        return f"Error checking error logs: {str(e)}"


@tool
def get_log_stats() -> str:
    """
    Get statistics about the collected logs.

    Use this to understand the overall logging health of the service.

    Returns:
        Statistics including total logs, level distribution, and top message patterns.
    """
    try:
        context = get_analysis_context()

        if not context.collected_data or not context.collected_data.logs:
            return json.dumps({
                "total_logs": 0,
                "message": "No log data available for this review period.",
            }, indent=2)

        logs = context.collected_data.logs

        # Count by level
        level_counts = {}
        for log in logs:
            level = log.level.upper()
            level_counts[level] = level_counts.get(level, 0) + 1

        # Get error count
        error_count = len(context.collected_data.errors) if context.collected_data.errors else 0

        stats = {
            "total_logs": len(logs),
            "level_distribution": level_counts,
            "error_types_count": error_count,
            "has_error_logs": level_counts.get("ERROR", 0) > 0,
            "has_warning_logs": level_counts.get("WARNING", 0) + level_counts.get("WARN", 0) > 0,
        }

        # Add assessment
        if level_counts.get("ERROR", 0) == 0 and error_count == 0:
            stats["assessment"] = "No errors logged in review period. Service appears healthy or errors may not be logged."
        elif level_counts.get("ERROR", 0) > 100:
            stats["assessment"] = "High error volume detected. Investigate error patterns."
        else:
            stats["assessment"] = "Normal log distribution."

        return json.dumps(stats, indent=2)

    except Exception as e:
        logger.exception(f"Error in get_log_stats: {e}")
        return f"Error getting log stats: {str(e)}"
