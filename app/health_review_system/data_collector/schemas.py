"""
Schemas for Data Collector Service.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    """A single log entry."""

    timestamp: datetime
    level: str
    message: str
    service: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)


class MetricsData(BaseModel):
    """Aggregated metrics for the review period."""

    latency_p50: Optional[float] = None
    latency_p90: Optional[float] = None
    latency_p99: Optional[float] = None
    error_rate: Optional[float] = None
    availability: Optional[float] = None
    throughput_per_minute: Optional[float] = None


class ErrorData(BaseModel):
    """Aggregated error data."""

    fingerprint: str
    error_type: str
    message_sample: str
    count: int
    first_seen: datetime
    last_seen: datetime
    endpoints: List[str] = Field(default_factory=list)
    stack_trace: Optional[str] = None


class CollectedData(BaseModel):
    """Result of data collection."""

    logs: List[LogEntry] = Field(default_factory=list)
    log_count: int = 0
    metrics: MetricsData = Field(default_factory=MetricsData)
    metric_count: int = 0
    errors: List[ErrorData] = Field(default_factory=list)
