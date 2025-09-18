from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class LogQueryRequest(BaseModel):
    workspace_id: str
    start_time_ms: Optional[int] = Field(None, description="Start time in milliseconds")
    end_time_ms: Optional[int] = Field(None, description="End time in milliseconds")
    severity_filter: Optional[List[str]] = Field(None, description="Filter by severity levels")
    search_query: Optional[str] = Field(None, description="Search text in log body")
    client_id: Optional[str] = Field(None, description="Filter by specific client ID")
    endpoint: Optional[str] = Field(None, description="Filter by endpoint")
    limit: int = Field(1000, ge=1, le=10000, description="Maximum number of logs to return")
    offset: int = Field(0, ge=0, description="Number of logs to skip")
    sort_order: str = Field("desc", pattern="^(asc|desc)$", description="Sort order by timestamp")


class LogQueryResponse(BaseModel):
    logs: List[Dict[str, Any]]
    total_count: int
    has_more: bool
    request_id: str
    execution_time_ms: float


class IngestionStatsResponse(BaseModel):
    batch_processor_stats: Dict[str, Any]
    clickhouse_health: bool
    otel_collector_status: str


class LogEntry(BaseModel):
    id: int
    workspace_id: str
    client_id: str
    timestamp_ms: int
    severity_text: str
    severity_number: int
    body: str
    resource_attributes: Dict[str, str]
    log_attributes: Dict[str, str]
    trace_id: str
    span_id: str
    endpoint: str
    service_name: str
    service_version: str
    ingested_at: datetime 