"""
Schemas for the rule engine output.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class DetectedProblem(BaseModel):
    """A gap/problem detected by the rule engine."""

    rule_id: str  # e.g., "LOG_001"
    problem_type: str  # "logging_gap" or "metrics_gap"
    severity: str  # "HIGH", "MEDIUM", "LOW"
    title: str
    category: str  # e.g., "error_handling", "performance", "observability"
    affected_files: List[str] = Field(default_factory=list)
    affected_functions: List[str] = Field(default_factory=list)
    evidence: List[dict] = Field(default_factory=list)
    # Metrics gap specific
    metric_type: Optional[str] = None  # "counter", "histogram", "gauge"
    suggested_metric_names: List[str] = Field(default_factory=list)


class RuleEngineResult(BaseModel):
    """Output of running all rules against extracted facts."""

    logging_gaps: List[DetectedProblem] = Field(default_factory=list)
    metrics_gaps: List[DetectedProblem] = Field(default_factory=list)
    facts_summary: dict = Field(default_factory=dict)
