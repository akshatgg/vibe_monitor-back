"""
Datadog Logs API Router
Provides OPEN endpoints for Datadog Logs operations (no authentication)
Designed for RCA bot integration
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from .schemas import (
    SearchLogsRequest,
    SearchLogsResponse,
    ListLogsRequest,
    ListLogsResponse,
    ListServicesRequest,
    ListServicesResponse,
)
from .service import datadog_logs_service

router = APIRouter(prefix="/datadog/logs", tags=["datadog-logs"])


@router.post("/search", response_model=SearchLogsResponse)
async def search_logs(
    request: SearchLogsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Search Datadog logs using the Logs Search API

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Uses Datadog credentials from workspace integration (API key + App key)
    - Searches logs using Datadog log search syntax
    - Supports time range filtering
    - Supports sorting and pagination
    - Returns full log data with attributes

    Query syntax examples:
    - "service:my-app" - Filter by service name
    - "status:error" - Filter by status level
    - "service:my-app status:error" - Multiple filters (AND)
    - "service:my-app OR service:other-app" - OR operator
    - "@http.status_code:500" - Filter by attribute
    - "error OR warning" - Text search with OR
    - "service:my-app -host:excluded" - Exclude with minus

    Time range:
    - from and to are in MILLISECONDS since epoch (not seconds!)
    - Example: for last 1 hour, use: from = (now - 3600) * 1000, to = now * 1000

    Returns:
    - data: List of log entries with full attributes
    - links: Pagination links if more results available
    - meta: Response metadata (elapsed time, status, warnings)
    - totalCount: Number of logs returned
    """
    try:
        response = await datadog_logs_service.search_logs(
            db=db,
            workspace_id=workspace_id,
            request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search logs: {str(e)}"
        )


@router.post("/list", response_model=ListLogsResponse)
async def list_logs(
    request: ListLogsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    List Datadog logs with simplified response format

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This is a simplified version of /search that returns a cleaner response format.
    Ideal for quick log viewing and analysis.

    This endpoint:
    - Uses Datadog credentials from workspace integration
    - Returns simplified log entries (timestamp, message, service, host, status, tags)
    - Easier to parse than the full search response
    - Same query syntax as /search endpoint

    Query examples:
    - "*" - Get all logs (default)
    - "service:my-app" - Filter by service
    - "status:error" - Filter by status
    - "error" - Text search

    Time range:
    - from_time and to_time are in MILLISECONDS since epoch

    Returns:
    - logs: List of simplified log entries
    - totalCount: Number of logs returned
    """
    try:
        response = await datadog_logs_service.list_logs(
            db=db,
            workspace_id=workspace_id,
            request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list logs: {str(e)}"
        )


@router.post("/services", response_model=ListServicesResponse)
async def list_services(
    request: ListServicesRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    List all unique service names from Datadog logs

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Queries logs in the specified time range
    - Extracts all unique service names
    - Returns sorted list of services
    - Useful for building filters or discovering what services are logging

    Time range:
    - from_time and to_time are in MILLISECONDS since epoch

    Limit:
    - Scans up to 'limit' logs to find services (default: 1000, max: 10000)
    - Higher limit = more accurate but slower
    - Lower limit = faster but might miss some services

    Returns:
    - services: Sorted list of unique service names
    - totalCount: Number of unique services found

    Example use cases:
    - Build a dropdown of available services for filtering
    - Discover what services are actively logging
    - RCA bot can see all services in the system
    """
    try:
        response = await datadog_logs_service.list_services(
            db=db,
            workspace_id=workspace_id,
            request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list services: {str(e)}"
        )
