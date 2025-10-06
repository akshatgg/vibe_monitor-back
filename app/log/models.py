"""
Data models for Loki logs responses
"""
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    """Single log entry with timestamp and line"""
    timestamp: str = Field(description="Timestamp in nanoseconds (Unix epoch)")
    line: str = Field(description="Log line content")


class LogStream(BaseModel):
    """Log stream with labels and entries"""
    stream: Dict[str, str] = Field(description="Stream labels (e.g., {job='app', level='error'})")
    values: List[List[str]] = Field(description="List of [timestamp, line] pairs")


class LogQueryData(BaseModel):
    """Data section of log query response"""
    resultType: Literal["streams"] = Field(description="Result type (always 'streams' for logs)")
    result: List[LogStream] = Field(description="Log streams")
    stats: Optional[Dict[str, Any]] = Field(default=None, description="Query statistics")


class LogQueryResponse(BaseModel):
    """Response for Loki log queries"""
    status: str = Field(description="Query status (success/error)")
    data: LogQueryData = Field(description="Query result data")


class LabelResponse(BaseModel):
    """Response for label queries"""
    status: str = Field(description="Query status")
    data: List[str] = Field(description="List of label names or values")


class LogQueryParams(BaseModel):
    """Parameters for log queries"""
    query: str = Field(description="LogQL query string")
    start: str = Field(description="Start time (RFC3339Nano or relative)")
    end: str = Field(description="End time (RFC3339Nano or relative)")
    limit: Optional[int] = Field(default=100, description="Max number of entries")
    direction: Optional[Literal["FORWARD", "BACKWARD"]] = Field(default="BACKWARD", description="Query direction")
    step: Optional[str] = Field(default=None, description="Query resolution step for metric queries")


class TimeRange(BaseModel):
    """Time range specification for log queries"""
    start: str = Field(description="Start time (RFC3339Nano, datetime, or relative like 'now-1h')")
    end: str = Field(description="End time (RFC3339Nano, datetime, or relative like 'now')")


class LogsHealthResponse(BaseModel):
    """Response model for logs health check"""
    status: str = Field(description="Health status")
    provider_type: str = Field(description="Current logs provider type")
    provider_healthy: bool = Field(description="Whether the provider is healthy")
