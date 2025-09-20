from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, List
from app.ingestion.schemas import LogQueryRequest, LogQueryResponse, IngestionStatsResponse
from app.ingestion.service import ingestion_service

router = APIRouter(prefix="", tags=["query_clickhouse"])


@router.post("/", response_model=LogQueryResponse)
async def query_logs(
    workspace_id: str = Body(..., description="Workspace ID"),
    start_time_ms: Optional[int] = Body(None, description="Start time in milliseconds"),
    end_time_ms: Optional[int] = Body(None, description="End time in milliseconds"),
    severity_filter: Optional[List[str]] = Body(None, description="Filter by severity levels"),
    search_query: Optional[str] = Body(None, description="Search text in log body"),
    client_id: Optional[str] = Body(None, description="Filter by specific client ID"),
    endpoint: Optional[str] = Body(None, description="Filter by endpoint"),
    limit: int = Body(1000, ge=1, le=10000, description="Maximum number of logs to return"),
    offset: int = Body(0, ge=0, description="Number of logs to skip"),
    sort_order: str = Body("desc", description="Sort order by timestamp (asc/desc)"),
):
    try:
        if sort_order not in ["asc", "desc"]:
            raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

        request = LogQueryRequest(
            workspace_id=workspace_id,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            severity_filter=severity_filter,
            search_query=search_query,
            client_id=client_id,
            endpoint=endpoint,
            limit=limit,
            offset=offset,
            sort_order=sort_order,
        )

        return await ingestion_service.query_logs(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query logs: {str(e)}")


@router.get("/time-range", response_model=LogQueryResponse)
async def query_logs_by_time_range(
    workspace_id: str = Query(..., description="Workspace ID"),
    start_time_ms: int = Query(..., description="Start time in milliseconds"),
    end_time_ms: int = Query(..., description="End time in milliseconds"),
    severity_filter: Optional[str] = Query(None, description="Comma-separated severity levels"),
    search_query: Optional[str] = Query(None, description="Search text in log body"),
    client_id: Optional[str] = Query(None, description="Filter by specific client ID"),
    endpoint: Optional[str] = Query(None, description="Filter by endpoint"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum number of logs to return"),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    sort_order: str = Query("desc", description="Sort order by timestamp (asc/desc)"),
):
    try:
        if sort_order not in ["asc", "desc"]:
            raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

        severity_list = severity_filter.split(",") if severity_filter else None

        request = LogQueryRequest(
            workspace_id=workspace_id,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            severity_filter=severity_list,
            search_query=search_query,
            client_id=client_id,
            endpoint=endpoint,
            limit=limit,
            offset=offset,
            sort_order=sort_order,
        )

        return await ingestion_service.query_logs(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query logs: {str(e)}")


@router.get("/search", response_model=LogQueryResponse)
async def search_logs(
    workspace_id: str = Query(..., description="Workspace ID"),
    search_query: str = Query(..., description="Search text in log body"),
    start_time_ms: Optional[int] = Query(None, description="Start time in milliseconds"),
    end_time_ms: Optional[int] = Query(None, description="End time in milliseconds"),
    severity_filter: Optional[str] = Query(None, description="Comma-separated severity levels"),
    client_id: Optional[str] = Query(None, description="Filter by specific client ID"),
    endpoint: Optional[str] = Query(None, description="Filter by endpoint"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum number of logs to return"),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    sort_order: str = Query("desc", description="Sort order by timestamp (asc/desc)"),
):
    try:
        if sort_order not in ["asc", "desc"]:
            raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

        severity_list = severity_filter.split(",") if severity_filter else None

        request = LogQueryRequest(
            workspace_id=workspace_id,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            severity_filter=severity_list,
            search_query=search_query,
            client_id=client_id,
            endpoint=endpoint,
            limit=limit,
            offset=offset,
            sort_order=sort_order,
        )

        return await ingestion_service.query_logs(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search logs: {str(e)}")





@router.get("/stats", response_model=IngestionStatsResponse)
async def get_ingestion_stats():
    try:
        return await ingestion_service.get_ingestion_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get ingestion stats: {str(e)}")


@router.get("/health")
async def health_check():
    try:
        stats = await ingestion_service.get_ingestion_stats()
        return {
            "status": "healthy" if stats.clickhouse_health else "degraded",
            "clickhouse": "connected" if stats.clickhouse_health else "disconnected",
            "otel_collector": stats.otel_collector_status,
            "batch_processor": {
                "running": stats.batch_processor_stats.get("running", False),
                "pending_logs": stats.batch_processor_stats.get("total_pending_logs", 0),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")