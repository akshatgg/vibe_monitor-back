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
    TimeRange,
    LabelResponse,
)
from .service import metrics_service
from ..core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


# Request/Response models for API endpoints
class CustomMetricRequest(BaseModel):
    """Request model for custom metric queries"""

    metric_name: str = Field(description="Name of the metric to query")
    service_name: Optional[str] = Field(
        default=None, description="Filter by service name"
    )
    labels: Optional[Dict[str, str]] = Field(
        default=None, description="Additional label filters"
    )
    timeout: Optional[str] = Field(default="30s", description="Query timeout")


class RangeMetricRequest(CustomMetricRequest):
    """Request model for range metric queries"""

    start_time: str = Field(
        description="Start time (ISO format or relative like 'now-1h')"
    )
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


# ==================== STANDALONE FUNCTIONS ====================
# These functions can be called directly without FastAPI dependencies
# =========================================================


async def get_metrics_health_func(workspace_id: Optional[str]) -> MetricsHealthResponse:
    """Get metrics system health status - Standalone function"""
    provider_healthy = await metrics_service.health_check(workspace_id)
    return MetricsHealthResponse(
        status="healthy" if provider_healthy else "unhealthy",
        provider_type="GrafanaProvider",
        provider_healthy=provider_healthy,
    )


async def get_metric_labels_func(workspace_id: str) -> LabelResponse:
    """Get list of all available metric label keys - Standalone function"""
    return await metrics_service.get_all_labels(workspace_id)


async def get_label_values_func(workspace_id: str, label_name: str) -> LabelResponse:
    """Get all values for a specific label - Standalone function"""
    return await metrics_service.get_label_values(workspace_id, label_name)


async def get_metric_names_func(workspace_id: str) -> List[str]:
    """Get list of all available metric names - Standalone function"""
    return await metrics_service.get_all_metric_names(workspace_id)


async def get_targets_status_func(workspace_id: str) -> TargetsResponse:
    """Get monitoring targets status - Standalone function"""
    return await metrics_service.get_targets_status(workspace_id)


async def query_instant_metrics_func(
    workspace_id: str, request: CustomMetricRequest
) -> InstantMetricResponse:
    """Query instant metric values - Standalone function"""
    return await metrics_service.get_instant_metrics(
        metric_name=request.metric_name,
        workspace_id=workspace_id,
        service_name=request.service_name,
        labels=request.labels,
        timeout=request.timeout,
    )


async def query_range_metrics_func(
    workspace_id: str, request: RangeMetricRequest
) -> RangeMetricResponse:
    """Query metric values over a time range - Standalone function"""
    time_range = TimeRange(
        start=request.start_time, end=request.end_time, step=request.step
    )
    return await metrics_service.get_range_metrics(
        metric_name=request.metric_name,
        time_range=time_range,
        workspace_id=workspace_id,
        service_name=request.service_name,
        labels=request.labels,
        timeout=request.timeout,
    )


async def get_cpu_metrics_func(
    workspace_id: str,
    service_name: Optional[str],
    start_time: str,
    end_time: str,
    step: str,
) -> RangeMetricResponse:
    """Get CPU usage metrics - Standalone function"""
    time_range = TimeRange(start=start_time, end=end_time, step=step)
    return await metrics_service.get_cpu_metrics(workspace_id, service_name, time_range)


async def get_memory_metrics_func(
    workspace_id: str,
    service_name: Optional[str],
    start_time: str,
    end_time: str,
    step: str,
) -> RangeMetricResponse:
    """Get memory usage metrics - Standalone function"""
    time_range = TimeRange(start=start_time, end=end_time, step=step)
    return await metrics_service.get_memory_metrics(
        workspace_id, service_name, time_range
    )


async def get_http_request_metrics_func(
    workspace_id: str,
    service_name: Optional[str],
    start_time: str,
    end_time: str,
    step: str,
) -> RangeMetricResponse:
    """Get HTTP request rate metrics - Standalone function"""
    time_range = TimeRange(start=start_time, end=end_time, step=step)
    return await metrics_service.get_http_request_metrics(
        workspace_id, service_name, time_range
    )


async def get_http_latency_metrics_func(
    workspace_id: str,
    service_name: Optional[str],
    percentile: float,
    start_time: str,
    end_time: str,
    step: str,
) -> RangeMetricResponse:
    """Get HTTP request latency metrics - Standalone function"""
    if not 0.0 <= percentile <= 1.0:
        raise ValueError("Percentile must be between 0.0 and 1.0")

    time_range = TimeRange(start=start_time, end=end_time, step=step)
    return await metrics_service.get_http_latency_metrics(
        workspace_id, service_name, time_range, percentile
    )


async def get_error_rate_metrics_func(
    workspace_id: str,
    service_name: Optional[str],
    start_time: str,
    end_time: str,
    step: str,
) -> RangeMetricResponse:
    """Get error rate metrics - Standalone function"""
    time_range = TimeRange(start=start_time, end=end_time, step=step)
    return await metrics_service.get_error_rate_metrics(
        workspace_id, service_name, time_range
    )


async def get_throughput_metrics_func(
    workspace_id: str,
    service_name: Optional[str],
    start_time: str,
    end_time: str,
    step: str,
) -> RangeMetricResponse:
    """Get throughput metrics - Standalone function"""
    time_range = TimeRange(start=start_time, end=end_time, step=step)
    return await metrics_service.get_throughput_metrics(
        workspace_id, service_name, time_range
    )


async def get_availability_metrics_func(
    workspace_id: str,
    service_name: Optional[str],
    start_time: str,
    end_time: str,
    step: str,
) -> RangeMetricResponse:
    """Get service availability metrics - Standalone function"""
    time_range = TimeRange(start=start_time, end=end_time, step=step)
    return await metrics_service.get_availability_metrics(
        workspace_id, service_name, time_range
    )


# ==================== FASTAPI ROUTER WRAPPER FUNCTIONS ====================
# These wrap the standalone functions with FastAPI dependencies
# =======================================================================


async def get_metrics_health_endpoint(
    workspace_id: Optional[str] = Header(None, alias="workspace-id"),
    service: Any = Depends(get_metrics_service),
) -> MetricsHealthResponse:
    """Get metrics system health status - FastAPI endpoint"""
    try:
        return await get_metrics_health_func(workspace_id)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Health check failed")


async def get_metric_labels_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service: Any = Depends(get_metrics_service),
) -> LabelResponse:
    """Get list of all available metric label keys - FastAPI endpoint"""
    try:
        return await get_metric_labels_func(workspace_id)
    except Exception as e:
        logger.error(f"Failed to get metric labels: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve metric labels")


async def get_label_values_endpoint(
    label_name: str,
    workspace_id: str = Header(..., alias="workspace-id"),
    service: Any = Depends(get_metrics_service),
) -> LabelResponse:
    """Get all values for a specific label - FastAPI endpoint"""
    try:
        return await get_label_values_func(workspace_id, label_name)
    except Exception as e:
        logger.error(f"Failed to get label values: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve label values")


async def get_metric_names_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service: Any = Depends(get_metrics_service),
) -> List[str]:
    """Get list of all available metric names - FastAPI endpoint"""
    try:
        return await get_metric_names_func(workspace_id)
    except Exception as e:
        logger.error(f"Failed to get metric names: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve metric names")


async def get_targets_status_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service: Any = Depends(get_metrics_service),
) -> TargetsResponse:
    """Get monitoring targets status - FastAPI endpoint"""
    try:
        return await get_targets_status_func(workspace_id)
    except Exception as e:
        logger.error(f"Failed to get targets status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve targets status")


async def query_instant_metrics_endpoint(
    request: CustomMetricRequest,
    workspace_id: str = Header(..., alias="workspace-id"),
    service: Any = Depends(get_metrics_service),
) -> InstantMetricResponse:
    """Query instant metric values - FastAPI endpoint"""
    try:
        return await query_instant_metrics_func(workspace_id, request)
    except Exception as e:
        logger.error(f"Failed to query instant metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to query instant metrics")


async def query_range_metrics_endpoint(
    request: RangeMetricRequest,
    workspace_id: str = Header(..., alias="workspace-id"),
    service: Any = Depends(get_metrics_service),
) -> RangeMetricResponse:
    """Query metric values over a time range - FastAPI endpoint"""
    try:
        return await query_range_metrics_func(workspace_id, request)
    except Exception as e:
        logger.error(f"Failed to query range metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to query range metrics")


async def get_cpu_metrics_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service),
) -> RangeMetricResponse:
    """Get CPU usage metrics - FastAPI endpoint"""
    try:
        return await get_cpu_metrics_func(
            workspace_id, service_name, start_time, end_time, step
        )
    except Exception as e:
        logger.error(f"Failed to get CPU metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve CPU metrics")


async def get_memory_metrics_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service),
) -> RangeMetricResponse:
    """Get memory usage metrics - FastAPI endpoint"""
    try:
        return await get_memory_metrics_func(
            workspace_id, service_name, start_time, end_time, step
        )
    except Exception as e:
        logger.error(f"Failed to get memory metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve memory metrics")


async def get_http_request_metrics_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service),
) -> RangeMetricResponse:
    """Get HTTP request rate metrics - FastAPI endpoint"""
    try:
        return await get_http_request_metrics_func(
            workspace_id, service_name, start_time, end_time, step
        )
    except Exception as e:
        logger.error(f"Failed to get HTTP request metrics: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve HTTP request metrics"
        )


async def get_http_latency_metrics_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    percentile: float = Query(0.95, description="Latency percentile (0.0-1.0)"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service),
) -> RangeMetricResponse:
    """Get HTTP request latency metrics - FastAPI endpoint"""
    try:
        return await get_http_latency_metrics_func(
            workspace_id, service_name, percentile, start_time, end_time, step
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get HTTP latency metrics: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve HTTP latency metrics"
        )


async def get_error_rate_metrics_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service),
) -> RangeMetricResponse:
    """Get error rate metrics - FastAPI endpoint"""
    try:
        return await get_error_rate_metrics_func(
            workspace_id, service_name, start_time, end_time, step
        )
    except Exception as e:
        logger.error(f"Failed to get error rate metrics: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve error rate metrics"
        )


async def get_throughput_metrics_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service),
) -> RangeMetricResponse:
    """Get throughput metrics - FastAPI endpoint"""
    try:
        return await get_throughput_metrics_func(
            workspace_id, service_name, start_time, end_time, step
        )
    except Exception as e:
        logger.error(f"Failed to get throughput metrics: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve throughput metrics"
        )


async def get_availability_metrics_endpoint(
    workspace_id: str = Header(..., alias="workspace-id"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    start_time: str = Query("now-1h", description="Start time"),
    end_time: str = Query("now", description="End time"),
    step: str = Query("60s", description="Query step"),
    service: Any = Depends(get_metrics_service),
) -> RangeMetricResponse:
    """Get service availability metrics - FastAPI endpoint"""
    try:
        return await get_availability_metrics_func(
            workspace_id, service_name, start_time, end_time, step
        )
    except Exception as e:
        logger.error(f"Failed to get availability metrics: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve availability metrics"
        )


# ==================== CONDITIONAL ROUTE REGISTRATION ====================
# Register routes only in local development
# In deployed envs (dev/prod), standalone functions remain available for LLM usage
# =======================================================================

if settings.is_local:
    logger.info(f"ENVIRONMENT={settings.ENVIRONMENT}: Registering metrics routes")

    router.add_api_route(
        "/health",
        get_metrics_health_endpoint,
        methods=["GET"],
        response_model=MetricsHealthResponse,
    )

    router.add_api_route(
        "/labels",
        get_metric_labels_endpoint,
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
        "/names", get_metric_names_endpoint, methods=["GET"], response_model=List[str]
    )

    router.add_api_route(
        "/targets",
        get_targets_status_endpoint,
        methods=["GET"],
        response_model=TargetsResponse,
    )

    router.add_api_route(
        "/query/instant",
        query_instant_metrics_endpoint,
        methods=["POST"],
        response_model=InstantMetricResponse,
    )

    router.add_api_route(
        "/query/range",
        query_range_metrics_endpoint,
        methods=["POST"],
        response_model=RangeMetricResponse,
    )

    router.add_api_route(
        "/cpu",
        get_cpu_metrics_endpoint,
        methods=["GET"],
        response_model=RangeMetricResponse,
    )

    router.add_api_route(
        "/memory",
        get_memory_metrics_endpoint,
        methods=["GET"],
        response_model=RangeMetricResponse,
    )

    router.add_api_route(
        "/http/requests",
        get_http_request_metrics_endpoint,
        methods=["GET"],
        response_model=RangeMetricResponse,
    )

    router.add_api_route(
        "/http/latency",
        get_http_latency_metrics_endpoint,
        methods=["GET"],
        response_model=RangeMetricResponse,
    )

    router.add_api_route(
        "/errors",
        get_error_rate_metrics_endpoint,
        methods=["GET"],
        response_model=RangeMetricResponse,
    )

    router.add_api_route(
        "/throughput",
        get_throughput_metrics_endpoint,
        methods=["GET"],
        response_model=RangeMetricResponse,
    )

    router.add_api_route(
        "/availability",
        get_availability_metrics_endpoint,
        methods=["GET"],
        response_model=RangeMetricResponse,
    )
else:
    logger.info(
        f"ENVIRONMENT={settings.ENVIRONMENT}: Metrics routes disabled (functions available for LLM usage)"
    )
