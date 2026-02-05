"""
Schemas for SLI Indicator Service.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class SLIData(BaseModel):
    """A single Service Level Indicator."""

    name: str  # e.g., "availability", "latency_p99", "error_rate", "throughput"
    category: str  # e.g., "reliability", "performance"
    score: int = Field(ge=0, le=100)
    previous_score: Optional[int] = None
    trend: Optional[str] = None  # "UP", "DOWN", "STABLE"
    target: Optional[str] = None  # e.g., "99.9%", "200ms"
    actual: Optional[str] = None  # e.g., "99.85%", "145ms"
    unit: Optional[str] = None  # e.g., "percent", "ms", "req/s"
    data_source: Optional[str] = None  # e.g., "newrelic", "datadog"
    query_used: Optional[str] = None
    analysis: Optional[str] = None


class SLIResult(BaseModel):
    """Result of SLI calculation."""

    slis: List[SLIData] = Field(default_factory=list)
