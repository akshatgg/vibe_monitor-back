"""
FastAPI router for logs endpoints
"""
import logging
from typing import Optional, Literal

from fastapi import APIRouter, HTTPException, Query, Depends, Header
from pydantic import BaseModel, Field

from .models import (
    LogQueryResponse,
    LabelResponse,
    LogQueryParams,
    TimeRange,
    LogsHealthResponse
)
from .service import logs_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/logs", tags=["logs"])


# Request models for API endpoints
class LogsQueryRequest(BaseModel):
    """Request model for custom log queries"""
    query: str = Field(description="LogQL query string")
    start: str = Field(description="Start time (RFC3339Nano or relative like 'now-1h')")
    end: str = Field(description="End time (RFC3339Nano or relative like 'now')")
    limit: Optional[int] = Field(default=100, description="Max number of log entries")
    direction: Optional[Literal["FORWARD", "BACKWARD"]] = Field(default="BACKWARD", description="Query direction")


class LogsSearchRequest(BaseModel):
    """Request model for log search"""
    search_term: str = Field(description="Text to search for in logs")
    service_name: Optional[str] = Field(default=None, description="Filter by service/job name")
    start: str = Field(default="now-1h", description="Start time")
    end: str = Field(default="now", description="End time")
    limit: Optional[int] = Field(default=100, description="Max number of log entries")


# Dependency to get logs service
async def get_logs_service():
    """Dependency to get the logs service instance"""
    return logs_service


@router.get("/health", response_model=LogsHealthResponse)
async def get_logs_health(
    workspace_id: Optional[str] = Header(None, alias="workspace-id"),
    service = Depends(get_logs_service)
) -> LogsHealthResponse:
    """Get logs system health status"""
    try:
        provider_healthy = await service.health_check(workspace_id)
        return LogsHealthResponse(
            status="healthy" if provider_healthy else "unhealthy",
            provider_type="LokiProvider",
            provider_healthy=provider_healthy
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Health check failed")


@router.get("/labels", response_model=LabelResponse)
async def get_log_labels(
    workspace_id: str = Header(..., alias="workspace-id"),
    service = Depends(get_logs_service)
) -> LabelResponse:
    """Get list of all available log labels"""
    try:
        return await service.get_all_labels(workspace_id)
    except Exception as e:
        logger.error(f"Failed to get log labels: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve log labels")


@router.get("/labels/{label_name}/values", response_model=LabelResponse)
async def get_label_values(
    label_name: str,
    workspace_id: str = Header(..., alias="workspace-id"),
    service = Depends(get_logs_service)
) -> LabelResponse:
    """Get all values for a specific label"""
    try:
        return await service.get_label_values(workspace_id, label_name)
    except Exception as e:
        logger.error(f"Failed to get label values: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve label values")


@router.post("/query", response_model=LogQueryResponse)
async def query_logs(
    request: LogsQueryRequest,
    workspace_id: str = Header(..., alias="workspace-id"),
    service = Depends(get_logs_service)
) -> LogQueryResponse:
    """Query logs with custom LogQL query"""
    try:
        params = LogQueryParams(
            query=request.query,
            start=request.start,
            end=request.end,
            limit=request.limit,
            direction=request.direction
        )
        return await service.query_logs(workspace_id, params)
    except Exception as e:
        logger.error(f"Failed to query logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to query logs")


@router.post("/search", response_model=LogQueryResponse)
async def search_logs(
    request: LogsSearchRequest,
    workspace_id: str = Header(..., alias="workspace-id"),
    service = Depends(get_logs_service)
) -> LogQueryResponse:
    """Search logs containing specific text"""
    try:
        time_range = TimeRange(start=request.start, end=request.end)
        return await service.search_logs(
            workspace_id=workspace_id,
            search_term=request.search_term,
            service_name=request.service_name,
            time_range=time_range,
            limit=request.limit
        )
    except Exception as e:
        logger.error(f"Failed to search logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to search logs")


# Convenience endpoints for common queries
@router.get("/service/{service_name}", response_model=LogQueryResponse)
async def get_service_logs(
    service_name: str,
    workspace_id: str = Header(..., alias="workspace-id"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    direction: Literal["FORWARD", "BACKWARD"] = Query("BACKWARD", description="Query direction"),
    service = Depends(get_logs_service)
) -> LogQueryResponse:
    """Get logs for a specific service"""
    try:
        time_range = TimeRange(start=start, end=end)
        return await service.get_logs_by_service(
            workspace_id=workspace_id,
            service_name=service_name,
            time_range=time_range,
            limit=limit,
            direction=direction
        )
    except Exception as e:
        logger.error(f"Failed to get service logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve service logs")


@router.get("/errors", response_model=LogQueryResponse)
async def get_error_logs(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    service = Depends(get_logs_service)
) -> LogQueryResponse:
    """Get error logs (filtered by error/ERROR keywords)"""
    try:
        time_range = TimeRange(start=start, end=end)
        return await service.get_error_logs(
            workspace_id=workspace_id,
            service_name=service_name,
            time_range=time_range,
            limit=limit
        )
    except Exception as e:
        logger.error(f"Failed to get error logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve error logs")


@router.get("/warnings", response_model=LogQueryResponse)
async def get_warning_logs(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    service = Depends(get_logs_service)
) -> LogQueryResponse:
    """Get warning logs (filtered by warn/WARNING keywords)"""
    try:
        time_range = TimeRange(start=start, end=end)
        return await service.get_warning_logs(
            workspace_id=workspace_id,
            service_name=service_name,
            time_range=time_range,
            limit=limit
        )
    except Exception as e:
        logger.error(f"Failed to get warning logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve warning logs")


@router.get("/info", response_model=LogQueryResponse)
async def get_info_logs(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    service = Depends(get_logs_service)
) -> LogQueryResponse:
    """Get info logs (filtered by info/INFO keywords)"""
    try:
        time_range = TimeRange(start=start, end=end)
        return await service.get_info_logs(
            workspace_id=workspace_id,
            service_name=service_name,
            time_range=time_range,
            limit=limit
        )
    except Exception as e:
        logger.error(f"Failed to get info logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve info logs")


@router.get("/debug", response_model=LogQueryResponse)
async def get_debug_logs(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    service = Depends(get_logs_service)
) -> LogQueryResponse:
    """Get debug logs (filtered by debug/DEBUG keywords)"""
    try:
        time_range = TimeRange(start=start, end=end)
        return await service.get_debug_logs(
            workspace_id=workspace_id,
            service_name=service_name,
            time_range=time_range,
            limit=limit
        )
    except Exception as e:
        logger.error(f"Failed to get debug logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve debug logs")


@router.get("/level/{log_level}", response_model=LogQueryResponse)
async def get_logs_by_level(
    log_level: str,
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    service = Depends(get_logs_service)
) -> LogQueryResponse:
    """Get logs filtered by custom log level"""
    try:
        time_range = TimeRange(start=start, end=end)
        return await service.get_logs_by_level(
            workspace_id=workspace_id,
            log_level=log_level,
            service_name=service_name,
            time_range=time_range,
            limit=limit
        )
    except Exception as e:
        logger.error(f"Failed to get logs by level: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve logs by level")
