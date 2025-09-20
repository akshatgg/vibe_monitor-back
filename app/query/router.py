from fastapi import APIRouter, HTTPException, Query, Header
from typing import Optional, List
from app.ingestion.schemas import LogQueryRequest, LogQueryResponse
from app.ingestion.service import ingestion_service

router = APIRouter(prefix="", tags=["query_clickhouse"])


@router.get("/logs", response_model=LogQueryResponse)
async def get_logs(
    workspace_id: str = Header(..., description="Workspace ID"),
    no_of_logs: int = Query(100, ge=1, le=10000, description="Number of logs to return (default: 100)"),
    search: Optional[str] = Query(None, description="Search keyword or sentence in log body"),
    timestamp_from: Optional[int] = Query(None, description="Start time in milliseconds"),
    timestamp_to: Optional[int] = Query(None, description="End time in milliseconds"),
    sort_order: str = Query("desc", description="Sort order by timestamp (asc/desc, default: desc)"),
    severity_filter: Optional[str] = Query(None, description="Comma-separated severity levels"),
    client_id: Optional[str] = Query(None, description="Filter by specific client ID"),
    endpoint: Optional[str] = Query(None, description="Filter by endpoint"),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
):
    try:
        if sort_order not in ["asc", "desc"]:
            raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

        severity_list = severity_filter.split(",") if severity_filter else None

        request = LogQueryRequest(
            workspace_id=workspace_id,
            start_time_ms=timestamp_from,
            end_time_ms=timestamp_to,
            severity_filter=severity_list,
            search_query=search,
            client_id=client_id,
            endpoint=endpoint,
            limit=no_of_logs,
            offset=offset,
            sort_order=sort_order,
        )

        return await ingestion_service.query_logs(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query logs: {str(e)}")





