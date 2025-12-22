"""
Pydantic schemas for CloudWatch Logs API
"""

from pydantic import BaseModel, Field
from typing import Optional, List


# ===== Log Groups Schemas =====


class LogGroupInfo(BaseModel):
    """Schema for a single log group"""

    logGroupName: str = Field(..., description="Log group name")
    creationTime: int = Field(..., description="Creation timestamp in milliseconds")
    arn: str = Field(..., description="Log group ARN")
    storedBytes: int = Field(..., description="Stored bytes in log group")
    logGroupClass: str = Field(
        ..., description="Log group class (STANDARD or INFREQUENT_ACCESS)"
    )
    logGroupArn: str = Field(..., description="Full log group ARN")
    metricFilterCount: Optional[int] = Field(
        None, description="Number of metric filters"
    )
    retentionInDays: Optional[int] = Field(None, description="Retention period in days")
    kmsKeyId: Optional[str] = Field(None, description="KMS key ID for encryption")


class ListLogGroupsRequest(BaseModel):
    """Request schema for listing log groups"""

    logGroupNamePrefix: Optional[str] = Field(
        None, description="Filter log groups by name prefix"
    )
    limit: Optional[int] = Field(
        100,
        description="Maximum number of log groups to return (default: 100)",
        ge=1,
        le=100,
    )


class ListLogGroupsResponse(BaseModel):
    """Response schema for listing log groups"""

    logGroups: List[LogGroupInfo] = Field(..., description="List of log groups")
    totalCount: int = Field(..., description="Total number of log groups returned")


# ===== Log Streams Schemas =====


class LogStreamInfo(BaseModel):
    """Schema for a single log stream"""

    logStreamName: str = Field(..., description="Log stream name")
    creationTime: int = Field(..., description="Creation timestamp in milliseconds")
    arn: str = Field(..., description="Log stream ARN")
    storedBytes: int = Field(..., description="Stored bytes in log stream")
    firstEventTimestamp: Optional[int] = Field(
        None, description="Timestamp of first event"
    )
    lastEventTimestamp: Optional[int] = Field(
        None, description="Timestamp of last event"
    )
    lastIngestionTime: Optional[int] = Field(
        None, description="Last ingestion timestamp"
    )


class ListLogStreamsRequest(BaseModel):
    """Request schema for listing log streams"""

    logGroupName: str = Field(..., description="Log group name to list streams from")
    logStreamNamePrefix: Optional[str] = Field(
        None, description="Filter streams by name prefix"
    )
    descending: Optional[bool] = Field(True, description="Descending order")
    limit: Optional[int] = Field(
        100,
        description="Maximum number of streams to return (default: 100)",
        ge=1,
        le=100,
    )


class ListLogStreamsResponse(BaseModel):
    """Response schema for listing log streams"""

    logStreams: List[LogStreamInfo] = Field(..., description="List of log streams")
    totalCount: int = Field(..., description="Total number of log streams returned")


# ===== Log Events Schemas =====


class LogEvent(BaseModel):
    """Schema for a single log event"""

    timestamp: int = Field(..., description="Event timestamp in milliseconds")
    message: str = Field(..., description="Log message")
    ingestionTime: int = Field(..., description="Ingestion timestamp in milliseconds")


class GetLogEventsRequest(BaseModel):
    """Request schema for getting log events"""

    logGroupName: str = Field(..., description="Log group name")
    logStreamName: str = Field(..., description="Log stream name")
    limit: Optional[int] = Field(
        100,
        description="Maximum number of events to return (default: 100)",
        ge=1,
        le=1000,
    )
    startTime: Optional[int] = Field(
        None, description="Start time in milliseconds since epoch"
    )
    endTime: Optional[int] = Field(
        None, description="End time in milliseconds since epoch"
    )


class GetLogEventsResponse(BaseModel):
    """Response schema for getting log events"""

    events: List[LogEvent] = Field(..., description="List of log events")
    totalCount: int = Field(..., description="Total number of log events returned")


# ===== CloudWatch Insights Query Schemas =====


class StartQueryRequest(BaseModel):
    """Request schema for starting a CloudWatch Insights query"""

    logGroupName: str = Field(..., description="Log group name to query")
    startTime: int = Field(..., description="Start time in seconds since epoch")
    endTime: int = Field(..., description="End time in seconds since epoch")
    queryString: str = Field(..., description="CloudWatch Insights query string")
    limit: Optional[int] = Field(
        1000, description="Maximum number of results", ge=1, le=10000
    )


class StartQueryResponse(BaseModel):
    """Response schema for starting a query"""

    queryId: str = Field(..., description="Query ID for retrieving results")


class QueryResultField(BaseModel):
    """Schema for a single field in query result"""

    field: str = Field(..., description="Field name")
    value: Optional[str] = Field(None, description="Field value")


class QueryStatistics(BaseModel):
    """Schema for query statistics"""

    recordsMatched: float = Field(..., description="Number of records matched")
    recordsScanned: float = Field(..., description="Number of records scanned")
    bytesScanned: float = Field(..., description="Number of bytes scanned")


class GetQueryResultsRequest(BaseModel):
    """Request schema for getting query results"""

    queryId: str = Field(..., description="Query ID from start_query")


class GetQueryResultsResponse(BaseModel):
    """Response schema for getting query results"""

    results: List[List[QueryResultField]] = Field(..., description="Query results")
    statistics: Optional[QueryStatistics] = Field(None, description="Query statistics")
    status: str = Field(
        ..., description="Query status: Scheduled, Running, Complete, Failed, Cancelled"
    )


# ===== Filter Log Events Schema =====


class FilterLogEventsRequest(BaseModel):
    """Request schema for filtering log events"""

    logGroupName: str = Field(..., description="Log group name")
    logStreamNames: Optional[List[str]] = Field(
        None, description="List of log stream names to filter"
    )
    startTime: Optional[int] = Field(
        None, description="Start time in milliseconds since epoch"
    )
    endTime: Optional[int] = Field(
        None, description="End time in milliseconds since epoch"
    )
    filterPattern: Optional[str] = Field(
        None, description="Filter pattern for log events"
    )
    limit: Optional[int] = Field(
        100, description="Maximum number of events (default: 100)", ge=1, le=1000
    )


class FilteredLogEvent(BaseModel):
    """Schema for a filtered log event"""

    logStreamName: str = Field(..., description="Log stream name")
    timestamp: int = Field(..., description="Event timestamp in milliseconds")
    message: str = Field(..., description="Log message")
    ingestionTime: int = Field(..., description="Ingestion timestamp")
    eventId: str = Field(..., description="Event ID")


class FilterLogEventsResponse(BaseModel):
    """Response schema for filtering log events"""

    events: List[FilteredLogEvent] = Field(..., description="Filtered log events")
    searchedLogStreams: Optional[List[dict]] = Field(
        None, description="Log streams that were searched"
    )
    totalCount: int = Field(..., description="Total number of events returned")
