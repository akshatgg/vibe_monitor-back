"""
Schemas for the rule engine output.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class DetectedProblem(BaseModel):
    """A gap/problem detected by the rule engine."""

    rule_id: str  # e.g., "LOG_001"
    problem_type: str  # "logging_gap" or "metrics_gap" or "red_gap"
    severity: str  # "HIGH", "MEDIUM", "LOW"
    title: str
    category: str  # e.g., "error_handling", "performance", "observability"
    affected_files: List[str] = Field(default_factory=list)
    affected_functions: List[str] = Field(default_factory=list)
    evidence: List[dict] = Field(default_factory=list)
    # Metrics gap specific
    metric_type: Optional[str] = None  # "counter", "histogram", "gauge"
    suggested_metric_names: List[str] = Field(default_factory=list)
    # RED gap specific — actionable fix suggestions
    suggestions: List[str] = Field(default_factory=list)


class REDMetricStatus(BaseModel):
    """Status of a single RED metric component."""

    signal: str  # "rate", "errors", "duration", "endpoint"
    chart: str  # "Chart 1 — Request Rate", etc.
    found: bool = False
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    metric_name: Optional[str] = None
    attributes_found: List[str] = Field(default_factory=list)
    attributes_missing: List[str] = Field(default_factory=list)
    details: Optional[str] = None


class REDDashboardReadiness(BaseModel):
    """Complete RED dashboard readiness report."""

    rate: REDMetricStatus = Field(
        default_factory=lambda: REDMetricStatus(
            signal="rate",
            chart="Chart 1 — Request Rate (HTTP Throughput)",
        )
    )
    errors: REDMetricStatus = Field(
        default_factory=lambda: REDMetricStatus(
            signal="errors",
            chart="Chart 2 — 4xx vs 5xx Error Rate",
        )
    )
    duration: REDMetricStatus = Field(
        default_factory=lambda: REDMetricStatus(
            signal="duration",
            chart="Chart 3 — API Latency (p50, p95, p99)",
        )
    )
    endpoint: REDMetricStatus = Field(
        default_factory=lambda: REDMetricStatus(
            signal="endpoint",
            chart="Chart 3 — Per-Endpoint Breakdown (Top 5 APIs)",
        )
    )
    is_red_ready: bool = False
    summary: str = ""


class RuleEngineResult(BaseModel):
    """Output of running all rules against extracted facts."""

    logging_gaps: List[DetectedProblem] = Field(default_factory=list)
    metrics_gaps: List[DetectedProblem] = Field(default_factory=list)
    red_gaps: List[DetectedProblem] = Field(default_factory=list)
    red_readiness: Optional[REDDashboardReadiness] = None
    facts_summary: dict = Field(default_factory=dict)
