"""
Pydantic schemas for New Relic Logs API
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict


# ===== Log Query Schemas =====


class QueryLogsRequest(BaseModel):
    """Request schema for querying New Relic logs using NRQL"""

    nrql_query: str = Field(
        ...,
        description="NRQL query string for logs (e.g., 'SELECT * FROM Log WHERE ...')",
    )


class LogResult(BaseModel):
    """Schema for a single log entry"""

    timestamp: Optional[int] = Field(None, description="Log timestamp in milliseconds")
    message: Optional[str] = Field(None, description="Log message content")
    attributes: Optional[Dict[str, Any]] = Field(
        None, description="Additional log attributes"
    )


class QueryLogsResponse(BaseModel):
    """Response schema for log query results"""

    results: List[Dict[str, Any]] = Field(
        ..., description="Query results as list of log entries"
    )
    totalCount: int = Field(..., description="Total number of results returned")
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Query metadata (e.g., performance stats)"
    )


# ===== Filter Logs Schemas =====


class FilterLogsRequest(BaseModel):
    """Request schema for filtering logs with common parameters"""

    query: str = Field(..., description="Search query or filter pattern")
    startTime: Optional[int] = Field(
        None, description="Start time in milliseconds since epoch"
    )
    endTime: Optional[int] = Field(
        None, description="End time in milliseconds since epoch"
    )
    limit: Optional[int] = Field(
        100, description="Maximum number of results (default: 100)", ge=1, le=1000
    )
    offset: Optional[int] = Field(
        0, description="Offset for pagination (default: 0)", ge=0
    )


class FilterLogsResponse(BaseModel):
    """Response schema for filtered logs"""

    logs: List[LogResult] = Field(..., description="Filtered log entries")
    totalCount: int = Field(..., description="Total number of results")
    hasMore: bool = Field(False, description="Whether more results are available")
