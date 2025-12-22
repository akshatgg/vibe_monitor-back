"""
Pydantic schemas for Datadog Logs API
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# ===== Logs Search Schemas =====

class SearchLogsRequest(BaseModel):
    """Request schema for searching Datadog logs"""
    query: str = Field(
        ...,
        description="Search query using Datadog log search syntax (e.g., 'service:my-app status:error')"
    )
    from_time: Optional[int] = Field(
        None,
        description="Start time in milliseconds since epoch (default: 2 hours ago)",
        alias="from"
    )
    to_time: Optional[int] = Field(
        None,
        description="End time in milliseconds since epoch (default: now)",
        alias="to"
    )
    limit: Optional[int] = Field(
        100,
        description="Maximum number of logs to return (default: 100, max: 1000)",
        ge=1,
        le=1000
    )
    sort: Optional[str] = Field(
        "desc",
        description="Sort order: 'asc' or 'desc' (default: 'desc')"
    )
    page_limit: Optional[int] = Field(
        None,
        description="Pagination limit",
        alias="page[limit]"
    )

    class Config:
        populate_by_name = True


class LogAttributes(BaseModel):
    """Schema for log attributes"""
    timestamp: Optional[str] = Field(None, description="Log timestamp")
    host: Optional[str] = Field(None, description="Host name")
    service: Optional[str] = Field(None, description="Service name")
    status: Optional[str] = Field(None, description="Log status level")
    message: Optional[str] = Field(None, description="Log message")
    tags: Optional[List[str]] = Field(None, description="Log tags")
    attributes: Optional[Dict[str, Any]] = Field(None, description="Custom attributes")


class LogData(BaseModel):
    """Schema for a single log entry"""
    id: str = Field(..., description="Log ID")
    type: str = Field(..., description="Log type")
    attributes: LogAttributes = Field(..., description="Log attributes")


class LogLinks(BaseModel):
    """Schema for pagination links"""
    next: Optional[str] = Field(None, description="Next page cursor")


class LogMeta(BaseModel):
    """Schema for metadata"""
    elapsed: Optional[int] = Field(None, description="Elapsed time in milliseconds")
    page: Optional[Dict[str, Any]] = Field(None, description="Page information")
    request_id: Optional[str] = Field(None, description="Request ID")
    status: Optional[str] = Field(None, description="Request status")
    warnings: Optional[List[Dict[str, Any]]] = Field(None, description="Warnings")


class SearchLogsResponse(BaseModel):
    """Response schema for searching logs"""
    data: List[LogData] = Field(..., description="List of log entries")
    links: Optional[LogLinks] = Field(None, description="Pagination links")
    meta: Optional[LogMeta] = Field(None, description="Response metadata")
    totalCount: int = Field(..., description="Total number of logs returned")


# ===== Aggregate Logs Schemas =====

class AggregateLogsRequest(BaseModel):
    """Request schema for aggregating Datadog logs"""
    query: str = Field(
        ...,
        description="Search query using Datadog log search syntax"
    )
    from_timestamp: Optional[int] = Field(
        None,
        description="Start time in milliseconds since epoch (default: 2 hours ago)",
        alias="from"
    )
    to_timestamp: Optional[int] = Field(
        None,
        description="End time in milliseconds since epoch (default: now)",
        alias="to"
    )
    compute: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Compute aggregations (e.g., count, cardinality, percentiles)"
    )
    filter_query: Optional[str] = Field(
        None,
        description="Additional filter query"
    )
    group_by: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Fields to group by"
    )

    class Config:
        populate_by_name = True


class AggregateLogsResponse(BaseModel):
    """Response schema for aggregate logs"""
    data: Optional[Dict[str, Any]] = Field(None, description="Aggregation results")
    meta: Optional[LogMeta] = Field(None, description="Response metadata")


# ===== List Logs Schemas (Simplified) =====

class ListLogsRequest(BaseModel):
    """Simplified request schema for listing logs"""
    query: str = Field(
        "*",
        description="Search query (use '*' for all logs)"
    )
    from_time: Optional[int] = Field(
        None,
        description="Start time in milliseconds since epoch (default: 2 hours ago)",
        alias="from"
    )
    to_time: Optional[int] = Field(
        None,
        description="End time in milliseconds since epoch (default: now)",
        alias="to"
    )
    service: Optional[str] = Field(
        None,
        description="Filter by service name"
    )
    status: Optional[str] = Field(
        None,
        description="Filter by status (error, warn, info, debug)"
    )
    limit: Optional[int] = Field(
        100,
        description="Maximum number of logs (default: 100, max: 1000)",
        ge=1,
        le=1000
    )

    class Config:
        populate_by_name = True


class SimplifiedLogEntry(BaseModel):
    """Simplified log entry schema"""
    timestamp: str = Field(..., description="Log timestamp")
    message: str = Field(..., description="Log message")
    service: Optional[str] = Field(None, description="Service name")
    host: Optional[str] = Field(None, description="Host name")
    status: Optional[str] = Field(None, description="Log status")
    tags: Optional[List[str]] = Field(None, description="Log tags")


class ListLogsResponse(BaseModel):
    """Simplified response schema for listing logs"""
    logs: List[SimplifiedLogEntry] = Field(..., description="List of logs")
    totalCount: int = Field(..., description="Total number of logs returned")


# ===== List Services Schemas =====

class ListServicesRequest(BaseModel):
    """Request schema for listing all unique services"""
    from_time: Optional[int] = Field(
        None,
        description="Start time in milliseconds since epoch (default: 24 hours ago)",
        alias="from"
    )
    to_time: Optional[int] = Field(
        None,
        description="End time in milliseconds since epoch (default: now)",
        alias="to"
    )
    limit: Optional[int] = Field(
        1000,
        description="Maximum number of logs to scan (default: 1000, max: 10000)",
        ge=1,
        le=10000
    )

    class Config:
        populate_by_name = True


class ListServicesResponse(BaseModel):
    """Response schema for listing services"""
    services: List[str] = Field(..., description="List of unique service names")
    totalCount: int = Field(..., description="Total number of unique services")
