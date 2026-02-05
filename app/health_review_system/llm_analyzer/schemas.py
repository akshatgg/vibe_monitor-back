"""
Schemas for LLM Analyzer Service.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class LoggingGap(BaseModel):
    """A detected logging gap."""

    description: str
    category: Optional[str] = None  # e.g., "error_handling", "business_logic"
    priority: str = "MEDIUM"  # HIGH, MEDIUM, LOW
    affected_files: List[str] = Field(default_factory=list)
    affected_functions: List[str] = Field(default_factory=list)
    suggested_locations: List[dict] = Field(default_factory=list)  # [{file, line}]
    suggested_log_statement: Optional[str] = None
    rationale: Optional[str] = None


class MetricsGap(BaseModel):
    """A detected metrics gap."""

    description: str
    category: Optional[str] = None  # e.g., "performance", "business"
    metric_type: Optional[str] = None  # e.g., "counter", "histogram", "gauge"
    priority: str = "MEDIUM"  # HIGH, MEDIUM, LOW
    affected_components: List[str] = Field(default_factory=list)
    suggested_metric_names: List[str] = Field(default_factory=list)
    implementation_guide: Optional[str] = None
    example_code: Optional[str] = None
    integration_provider: Optional[str] = None  # e.g., "datadog", "newrelic"


class AnalyzedError(BaseModel):
    """An analyzed error with root cause insights."""

    error_type: str
    fingerprint: str
    count: int
    severity: str = "MEDIUM"  # HIGH, MEDIUM, LOW
    likely_cause: Optional[str] = None
    code_location: Optional[str] = None


class AnalysisResult(BaseModel):
    """Result of LLM analysis."""

    logging_gaps: List[LoggingGap] = Field(default_factory=list)
    metrics_gaps: List[MetricsGap] = Field(default_factory=list)
    analyzed_errors: List[AnalyzedError] = Field(default_factory=list)
    summary: str = ""
    recommendations: str = ""
