"""
FastAPI router for metrics endpoints
"""
import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends, Header
from pydantic import BaseModel, Field

from .models import (
    InstantMetricResponse,
    RangeMetricResponse,
    TargetsResponse,
    TimeRange
)
from .service import metrics_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


# Request/Response models for API endpoints
class CustomMetricRequest(BaseModel):
    """Request model for custom metric queries"""
    metric_name: str = Field(description="Name of the metric to query")
    service_name: Optional[str] = Field(default=None, description="Filter by service name")
    labels: Optional[Dict[str, str]] = Field(default=None, description="Additional label filters")
    timeout: Optional[str] = Field(default="30s", description="Query timeout")


class RangeMetricRequest(CustomMetricRequest):
    """Request model for range metric queries"""
    start_time: str = Field(description="Start time (ISO format or relative like 'now-1h')")
    end_time: str = Field(description="End time (ISO format or relative like 'now')")
    step: Optional[str] = Field(default="60s", description="Query resolution step")


class MetricsHealthResponse(BaseModel):
    """Response model for metrics health check"""
    status: str = Field(description="Health status")
    provider_type: str = Field(description="Current metrics provider type")
    provider_healthy: bool = Field(description="Whether the provider is healthy")


# Dependency to get metrics service
async def get_metrics_service():
    """Dependency to get the metrics service instance"""
    return metrics_service


@router.get("/health", response_model=MetricsHealthResponse)
async def get_metrics_health(
    workspace_id: Optional[str] = Header(None, alias="workspace-id"),
    service: Any = Depends(get_metrics_service)
) -> MetricsHealthResponse:
    """Get metrics system health status"""
    try:
        provider_healthy = await service.health_check(workspace_id)
        return MetricsHealthResponse(
            status="healthy" if provider_healthy else "unhealthy",
            provider_type="GrafanaProvider",
            provider_healthy=provider_healthy
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Health check failed")


@router.get("/names", response_model=List[str])
async def get_metric_names(
    workspace_id: str = Header(..., alias="workspace-id"),
    service: Any = Depends(get_metrics_service)
) -> List[str]:
    """Get list of all available metric names"""
    try:
        return await service.get_all_metric_names(workspace_id)
    except Exception as e:
        logger.error(f"Failed to get metric names: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve metric names")


@router.get("/targets", response_model=TargetsResponse)
async def get_targets_status(
    workspace_id: str = Header(..., alias="workspace-id"),
    service: Any = Depends(get_metrics_service)
) -> TargetsResponse:
    """Get monitoring targets status"""
    try:
        return await service.get_targets_status(workspace_id)
    except Exception as e:
        logger.error(f"Failed to get targets status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve targets status")


@router.post("/query/instant", response_model=InstantMetricResponse)
async def query_instant_metrics(
    request: CustomMetricRequest,
    workspace_id: str = Header(..., alias="workspace-id"),
    service: Any = Depends(get_metrics_service)
) -> InstantMetricResponse:
    """Query instant metric values"""
    try:
        return await service.get_instant_metrics(
            metric_name=request.metric_name,
            workspace_id=workspace_id,
            service_name=request.service_name,
            labels=request.labels,
            timeout=request.timeout
        )
    except Exception as e:
        logger.error(f"Failed to query instant metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to query instant metrics")


@router.post("/query/range", response_model=RangeMetricResponse)
async def query_range_metrics(
    request: RangeMetricRequest,
    workspace_id: str = Header(..., alias="workspace-id"),
    service: Any = Depends(get_metrics_service)
) -> RangeMetricResponse:
    """Query metric values over a time range"""
    try:
        time_range = TimeRange(
            start=request.start_time,
            end=request.end_time,
            step=request.step
        )

        return await service.get_range_metrics(
            metric_name=request.metric_name,
            time_range=time_range,
            workspace_id=workspace_id,
            service_name=request.service_name,
            labels=request.labels,
            timeout=request.timeout
        )
    except Exception as e:
        logger.error(f"Failed to query range metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to query range metrics")


# Convenience endpoints for common metrics
@router.get("/cpu", response_model=RangeMetricResponse)
async def get_cpu_metrics(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service)
) -> RangeMetricResponse:
    """Get CPU usage metrics"""
    try:
        time_range = TimeRange(start=start_time, end=end_time, step=step)
        return await service.get_cpu_metrics(workspace_id, service_name, time_range)
    except Exception as e:
        logger.error(f"Failed to get CPU metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve CPU metrics")


@router.get("/memory", response_model=RangeMetricResponse)
async def get_memory_metrics(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service)
) -> RangeMetricResponse:
    """Get memory usage metrics"""
    try:
        time_range = TimeRange(start=start_time, end=end_time, step=step)
        return await service.get_memory_metrics(workspace_id, service_name, time_range)
    except Exception as e:
        logger.error(f"Failed to get memory metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve memory metrics")


@router.get("/http/requests", response_model=RangeMetricResponse)
async def get_http_request_metrics(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service)
) -> RangeMetricResponse:
    """Get HTTP request rate metrics"""
    try:
        time_range = TimeRange(start=start_time, end=end_time, step=step)
        return await service.get_http_request_metrics(workspace_id, service_name, time_range)
    except Exception as e:
        logger.error(f"Failed to get HTTP request metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve HTTP request metrics")


@router.get("/http/latency", response_model=RangeMetricResponse)
async def get_http_latency_metrics(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    percentile: float = Query(0.95, description="Latency percentile (0.0-1.0)"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service)
) -> RangeMetricResponse:
    """Get HTTP request latency metrics"""
    try:
        if not 0.0 <= percentile <= 1.0:
            raise HTTPException(status_code=400, detail="Percentile must be between 0.0 and 1.0")

        time_range = TimeRange(start=start_time, end=end_time, step=step)
        return await service.get_http_latency_metrics(workspace_id, service_name, time_range, percentile)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get HTTP latency metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve HTTP latency metrics")


@router.get("/errors", response_model=RangeMetricResponse)
async def get_error_rate_metrics(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service)
) -> RangeMetricResponse:
    """Get error rate metrics"""
    try:
        time_range = TimeRange(start=start_time, end=end_time, step=step)
        return await service.get_error_rate_metrics(workspace_id, service_name, time_range)
    except Exception as e:
        logger.error(f"Failed to get error rate metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve error rate metrics")


@router.get("/throughput", response_model=RangeMetricResponse)
async def get_throughput_metrics(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service)
) -> RangeMetricResponse:
    """Get throughput metrics"""
    try:
        time_range = TimeRange(start=start_time, end=end_time, step=step)
        return await service.get_throughput_metrics(workspace_id, service_name, time_range)
    except Exception as e:
        logger.error(f"Failed to get throughput metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve throughput metrics")


@router.get("/availability", response_model=RangeMetricResponse)
async def get_availability_metrics(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service)
) -> RangeMetricResponse:
    """Get service availability metrics"""
    try:
        time_range = TimeRange(start=start_time, end=end_time, step=step)
        return await service.get_availability_metrics(workspace_id, service_name, time_range)
    except Exception as e:
        logger.error(f"Failed to get availability metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve availability metrics")