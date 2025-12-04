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
    LogsHealthResponse,
)
from .service import logs_service
from ..core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/logs", tags=["logs"])


# Request models for API endpoints
class LogsQueryRequest(BaseModel):
    """Request model for custom log queries"""

    query: str = Field(description="LogQL query string")
    start: str = Field(description="Start time (RFC3339Nano or relative like 'now-1h')")
    end: str = Field(description="End time (RFC3339Nano or relative like 'now')")
    limit: Optional[int] = Field(default=100, description="Max number of log entries")
    direction: Optional[Literal["FORWARD", "BACKWARD"]] = Field(
        default="BACKWARD", description="Query direction"
    )


class LogsSearchRequest(BaseModel):
    """Request model for log search"""

    search_term: str = Field(description="Text to search for in logs")
    service_name: Optional[str] = Field(
        default=None, description="Filter by service/job name"
    )
    start: str = Field(default="now-1h", description="Start time")
    end: str = Field(default="now", description="End time")
    limit: Optional[int] = Field(default=100, description="Max number of log entries")


# Dependency to get logs service
async def get_logs_service():
    """Dependency to get the logs service instance"""
    return logs_service


# ==================== STANDALONE FUNCTIONS ====================
# These functions can be called directly without FastAPI dependencies
# =========================================================


async def get_logs_health_func(workspace_id: Optional[str]) -> LogsHealthResponse:
    """Get logs system health status - Standalone function"""
    provider_healthy = await logs_service.health_check(workspace_id)
    return LogsHealthResponse(
        status="healthy" if provider_healthy else "unhealthy",
        provider_type="LokiProvider",
        provider_healthy=provider_healthy,
    )


async def get_log_labels_func(workspace_id: str) -> LabelResponse:
    """Get list of all available log labels - Standalone function"""
    return await logs_service.get_all_labels(workspace_id)


async def get_label_values_func(workspace_id: str, label_name: str) -> LabelResponse:
    """Get all values for a specific label - Standalone function"""
    return await logs_service.get_label_values(workspace_id, label_name)


async def query_logs_func(
    workspace_id: str, request: LogsQueryRequest
) -> LogQueryResponse:
    """Query logs with custom LogQL query - Standalone function"""
    params = LogQueryParams(
        query=request.query,
        start=request.start,
        end=request.end,
        limit=request.limit,
        direction=request.direction,
    )
    return await logs_service.query_logs(workspace_id, params)


async def search_logs_func(
    workspace_id: str, request: LogsSearchRequest
) -> LogQueryResponse:
    """Search logs containing specific text - Standalone function"""
    time_range = TimeRange(start=request.start, end=request.end)
    return await logs_service.search_logs(
        workspace_id=workspace_id,
        search_term=request.search_term,
        service_name=request.service_name,
        time_range=time_range,
        limit=request.limit,
    )


async def get_service_logs_func(
    workspace_id: str,
    service_name: str,
    start: str,
    end: str,
    limit: int,
    direction: Literal["FORWARD", "BACKWARD"],
) -> LogQueryResponse:
    """Get logs for a specific service - Standalone function"""
    time_range = TimeRange(start=start, end=end)
    return await logs_service.get_logs_by_service(
        workspace_id=workspace_id,
        service_name=service_name,
        time_range=time_range,
        limit=limit,
        direction=direction,
    )


async def get_error_logs_func(
    workspace_id: str, service_name: Optional[str], start: str, end: str, limit: int
) -> LogQueryResponse:
    """Get error logs (filtered by error/ERROR keywords) - Standalone function"""
    time_range = TimeRange(start=start, end=end)
    return await logs_service.get_error_logs(
        workspace_id=workspace_id,
        service_name=service_name,
        time_range=time_range,
        limit=limit,
    )


async def get_warning_logs_func(
    workspace_id: str, service_name: Optional[str], start: str, end: str, limit: int
) -> LogQueryResponse:
    """Get warning logs (filtered by warn/WARNING keywords) - Standalone function"""
    time_range = TimeRange(start=start, end=end)
    return await logs_service.get_warning_logs(
        workspace_id=workspace_id,
        service_name=service_name,
        time_range=time_range,
        limit=limit,
    )


async def get_info_logs_func(
    workspace_id: str, service_name: Optional[str], start: str, end: str, limit: int
) -> LogQueryResponse:
    """Get info logs (filtered by info/INFO keywords) - Standalone function"""
    time_range = TimeRange(start=start, end=end)
    return await logs_service.get_info_logs(
        workspace_id=workspace_id,
        service_name=service_name,
        time_range=time_range,
        limit=limit,
    )


async def get_debug_logs_func(
    workspace_id: str, service_name: Optional[str], start: str, end: str, limit: int
) -> LogQueryResponse:
    """Get debug logs (filtered by debug/DEBUG keywords) - Standalone function"""
    time_range = TimeRange(start=start, end=end)
    return await logs_service.get_debug_logs(
        workspace_id=workspace_id,
        service_name=service_name,
        time_range=time_range,
        limit=limit,
    )


async def get_logs_by_level_func(
    workspace_id: str,
    log_level: str,
    service_name: Optional[str],
    start: str,
    end: str,
    limit: int,
) -> LogQueryResponse:
    """Get logs filtered by custom log level - Standalone function"""
    time_range = TimeRange(start=start, end=end)
    return await logs_service.get_logs_by_level(
        workspace_id=workspace_id,
        log_level=log_level,
        service_name=service_name,
        time_range=time_range,
        limit=limit,
    )


# ==================== FASTAPI ROUTER WRAPPER FUNCTIONS ====================
# These wrap the standalone functions with FastAPI dependencies
# =======================================================================


async def get_logs_health_endpoint(
    workspace_id: Optional[str] = Header(None, alias="workspace-id"),
    service=Depends(get_logs_service),
) -> LogsHealthResponse:
    """Get logs system health status - FastAPI endpoint"""
    try:
        return await get_logs_health_func(workspace_id)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Health check failed")


async def get_log_labels_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service=Depends(get_logs_service),
) -> LabelResponse:
    """Get list of all available log labels - FastAPI endpoint"""
    try:
        return await get_log_labels_func(workspace_id)
    except Exception as e:
        logger.error(f"Failed to get log labels: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve log labels")


async def get_label_values_endpoint(
    label_name: str,
    workspace_id: str = Header(..., alias="workspace-id"),
    service=Depends(get_logs_service),
) -> LabelResponse:
    """Get all values for a specific label - FastAPI endpoint"""
    try:
        return await get_label_values_func(workspace_id, label_name)
    except Exception as e:
        logger.error(f"Failed to get label values: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve label values")


async def query_logs_endpoint(
    request: LogsQueryRequest,
    workspace_id: str = Header(..., alias="workspace-id"),
    service=Depends(get_logs_service),
) -> LogQueryResponse:
    """Query logs with custom LogQL query - FastAPI endpoint"""
    try:
        return await query_logs_func(workspace_id, request)
    except Exception as e:
        logger.error(f"Failed to query logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to query logs")


async def search_logs_endpoint(
    request: LogsSearchRequest,
    workspace_id: str = Header(..., alias="workspace-id"),
    service=Depends(get_logs_service),
) -> LogQueryResponse:
    """Search logs containing specific text - FastAPI endpoint"""
    try:
        return await search_logs_func(workspace_id, request)
    except Exception as e:
        logger.error(f"Failed to search logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to search logs")


async def get_service_logs_endpoint(
    service_name: str,
    workspace_id: str = Header(..., alias="workspace-id"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    direction: Literal["FORWARD", "BACKWARD"] = Query(
        "BACKWARD", description="Query direction"
    ),
    service=Depends(get_logs_service),
) -> LogQueryResponse:
    """Get logs for a specific service - FastAPI endpoint"""
    try:
        return await get_service_logs_func(
            workspace_id, service_name, start, end, limit, direction
        )
    except Exception as e:
        logger.error(f"Failed to get service logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve service logs")


async def get_error_logs_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    service=Depends(get_logs_service),
) -> LogQueryResponse:
    """Get error logs (filtered by error/ERROR keywords) - FastAPI endpoint"""
    try:
        return await get_error_logs_func(workspace_id, service_name, start, end, limit)
    except Exception as e:
        logger.error(f"Failed to get error logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve error logs")


async def get_warning_logs_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    service=Depends(get_logs_service),
) -> LogQueryResponse:
    """Get warning logs (filtered by warn/WARNING keywords) - FastAPI endpoint"""
    try:
        return await get_warning_logs_func(
            workspace_id, service_name, start, end, limit
        )
    except Exception as e:
        logger.error(f"Failed to get warning logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve warning logs")


async def get_info_logs_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    service=Depends(get_logs_service),
) -> LogQueryResponse:
    """Get info logs (filtered by info/INFO keywords) - FastAPI endpoint"""
    try:
        return await get_info_logs_func(workspace_id, service_name, start, end, limit)
    except Exception as e:
        logger.error(f"Failed to get info logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve info logs")


async def get_debug_logs_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    service=Depends(get_logs_service),
) -> LogQueryResponse:
    """Get debug logs (filtered by debug/DEBUG keywords) - FastAPI endpoint"""
    try:
        return await get_debug_logs_func(workspace_id, service_name, start, end, limit)
    except Exception as e:
        logger.error(f"Failed to get debug logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve debug logs")


async def get_logs_by_level_endpoint(
    log_level: str,
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start: str = Query("now-1h", description="Start time"),
    end: str = Query("now", description="End time"),
    limit: int = Query(100, description="Max number of entries"),
    service=Depends(get_logs_service),
) -> LogQueryResponse:
    """Get logs filtered by custom log level - FastAPI endpoint"""
    try:
        return await get_logs_by_level_func(
            workspace_id, log_level, service_name, start, end, limit
        )
    except Exception as e:
        logger.error(f"Failed to get logs by level: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve logs by level")


# ==================== CONDITIONAL ROUTE REGISTRATION ====================
# Register routes only in local development
# In deployed envs (dev/prod), standalone functions remain available for LLM usage
# =======================================================================

if settings.is_local:
    logger.info(f"ENVIRONMENT={settings.ENVIRONMENT}: Registering logs routes")

    router.add_api_route(
        "/health",
        get_logs_health_endpoint,
        methods=["GET"],
        response_model=LogsHealthResponse,
    )

    router.add_api_route(
        "/labels",
        get_log_labels_endpoint,
        methods=["GET"],
        response_model=LabelResponse,
    )

    router.add_api_route(
        "/labels/{label_name}/values",
        get_label_values_endpoint,
        methods=["GET"],
        response_model=LabelResponse,
    )

    router.add_api_route(
        "/query", query_logs_endpoint, methods=["POST"], response_model=LogQueryResponse
    )

    router.add_api_route(
        "/search",
        search_logs_endpoint,
        methods=["POST"],
        response_model=LogQueryResponse,
    )

    router.add_api_route(
        "/service/{service_name}",
        get_service_logs_endpoint,
        methods=["GET"],
        response_model=LogQueryResponse,
    )

    router.add_api_route(
        "/errors",
        get_error_logs_endpoint,
        methods=["GET"],
        response_model=LogQueryResponse,
    )

    router.add_api_route(
        "/warnings",
        get_warning_logs_endpoint,
        methods=["GET"],
        response_model=LogQueryResponse,
    )

    router.add_api_route(
        "/info",
        get_info_logs_endpoint,
        methods=["GET"],
        response_model=LogQueryResponse,
    )

    router.add_api_route(
        "/debug",
        get_debug_logs_endpoint,
        methods=["GET"],
        response_model=LogQueryResponse,
    )

    router.add_api_route(
        "/level/{log_level}",
        get_logs_by_level_endpoint,
        methods=["GET"],
        response_model=LogQueryResponse,
    )
else:
    logger.info(
        f"ENVIRONMENT={settings.ENVIRONMENT}: Logs routes disabled (functions available for LLM usage)"
    )
