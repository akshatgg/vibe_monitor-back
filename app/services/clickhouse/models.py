from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime
import time


class LogEntry(BaseModel):
    id: int = Field(default_factory=lambda: int(time.time_ns()))
    workspace_id: str
    client_id: str
    timestamp_ms: int
    severity_text: str = Field(default="INFO")
    severity_number: int = Field(default=9)
    body: str
    resource_attributes: Dict[str, str] = Field(default_factory=dict)
    log_attributes: Dict[str, str] = Field(default_factory=dict)
    trace_id: str = Field(default="")
    span_id: str = Field(default="")
    endpoint: str = Field(default="")
    service_name: str = Field(default="")
    service_version: str = Field(default="")

    class Config:
        json_encoders = {
            datetime: lambda v: int(v.timestamp() * 1000)
        }


class LogQueryFilters(BaseModel):
    workspace_id: str
    start_time_ms: Optional[int] = None
    end_time_ms: Optional[int] = None
    severity_filter: Optional[list[str]] = None
    search_query: Optional[str] = None
    client_id: Optional[str] = None
    endpoint: Optional[str] = None
    limit: int = Field(default=1000, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")


class LogQueryResponse(BaseModel):
    logs: list[Dict[str, Any]]
    total_count: int
    has_more: bool
    filters_applied: LogQueryFilters