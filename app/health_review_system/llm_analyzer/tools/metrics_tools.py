"""
Metrics Analysis Tools for LLM Analyzer.

Tools for analyzing collected metrics data.
"""

import json
import logging

from langchain_core.tools import tool

from app.health_review_system.llm_analyzer.tools.base import get_analysis_context

logger = logging.getLogger(__name__)


@tool
def get_current_metrics() -> str:
    """
    Get the current metrics for the service.

    Returns latency percentiles, error rate, availability, and throughput.
    Use this to understand the service's current performance and reliability.

    Returns:
        JSON object with all available metrics.
    """
    try:
        context = get_analysis_context()

        if not context.collected_data or not context.collected_data.metrics:
            return json.dumps({
                "available": False,
                "message": "No metrics data available for this service.",
            }, indent=2)

        metrics = context.collected_data.metrics

        result = {
            "available": True,
            "latency": {
                "p50_ms": metrics.latency_p50,
                "p90_ms": metrics.latency_p90,
                "p99_ms": metrics.latency_p99,
            },
            "reliability": {
                "error_rate_percent": round(metrics.error_rate * 100, 4) if metrics.error_rate else None,
                "availability_percent": metrics.availability,
            },
            "throughput": {
                "requests_per_minute": metrics.throughput_per_minute,
            },
        }

        # Add assessments
        assessments = []

        if metrics.latency_p99 and metrics.latency_p99 > 500:
            assessments.append(f"High p99 latency ({metrics.latency_p99}ms > 500ms target)")

        if metrics.error_rate and metrics.error_rate > 0.01:
            assessments.append(f"Elevated error rate ({metrics.error_rate * 100:.2f}% > 1% target)")

        if metrics.availability and metrics.availability < 99.9:
            assessments.append(f"Below availability target ({metrics.availability}% < 99.9%)")

        result["assessments"] = assessments if assessments else ["All metrics within normal ranges"]

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.exception(f"Error in get_current_metrics: {e}")
        return f"Error getting metrics: {str(e)}"


@tool
def get_metrics_summary() -> str:
    """
    Get a summary of what metrics are available and what might be missing.

    Use this to identify potential metrics gaps - areas where instrumentation
    should be added.

    Returns:
        Summary of available metrics and recommendations for gaps.
    """
    try:
        context = get_analysis_context()

        if not context.collected_data or not context.collected_data.metrics:
            return json.dumps({
                "has_metrics": False,
                "gap_assessment": "No metrics data available. This is a significant observability gap.",
                "recommendations": [
                    "Add basic HTTP metrics (request count, latency histogram, error rate)",
                    "Configure Prometheus/Datadog integration for metrics collection",
                ],
            }, indent=2)

        metrics = context.collected_data.metrics

        available = []
        missing = []

        # Check what's available
        if metrics.latency_p50 is not None:
            available.append("latency_p50")
        else:
            missing.append("latency_p50")

        if metrics.latency_p99 is not None:
            available.append("latency_p99")
        else:
            missing.append("latency_p99")

        if metrics.error_rate is not None:
            available.append("error_rate")
        else:
            missing.append("error_rate")

        if metrics.availability is not None:
            available.append("availability")
        else:
            missing.append("availability")

        if metrics.throughput_per_minute is not None:
            available.append("throughput")
        else:
            missing.append("throughput")

        # Common metrics that might be missing
        recommended_metrics = [
            "database query latency",
            "external API call latency",
            "cache hit/miss ratio",
            "queue depth",
            "background job duration",
        ]

        result = {
            "has_metrics": True,
            "available_metrics": available,
            "missing_basic_metrics": missing,
            "recommended_additional_metrics": recommended_metrics,
        }

        if missing:
            result["gap_assessment"] = f"Missing basic metrics: {', '.join(missing)}. These should be added for better observability."
        else:
            result["gap_assessment"] = "Basic metrics are available. Consider adding business-specific metrics."

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.exception(f"Error in get_metrics_summary: {e}")
        return f"Error getting metrics summary: {str(e)}"
