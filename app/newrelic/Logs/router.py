"""
New Relic Logs API Router
Provides OPEN endpoints for New Relic Logs operations (no authentication)
Designed for RCA bot integration and testing
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from .schemas import (
    QueryLogsRequest,
    QueryLogsResponse,
    FilterLogsRequest,
    FilterLogsResponse,
)
from .service import newrelic_logs_service

router = APIRouter(prefix="/newrelic/logs", tags=["newrelic-logs"])


@router.post("/query", response_model=QueryLogsResponse)
async def query_logs(
    request: QueryLogsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Query New Relic logs using NRQL

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Executes NRQL queries against New Relic Logs
    - Uses workspace's stored New Relic credentials
    - Supports full NRQL syntax for logs
    - Returns raw query results

    NRQL Query Examples:
    - "SELECT * FROM Log WHERE message LIKE '%error%' SINCE 1 hour ago"
    - "SELECT message, timestamp FROM Log WHERE service.name = 'my-app' LIMIT 50"
    - "SELECT count(*) FROM Log WHERE logtype = 'application' FACET level SINCE 1 day ago"
    - "SELECT * FROM Log WHERE error IS NOT NULL SINCE 2 hours ago UNTIL 1 hour ago"

    Time Syntax:
    - Absolute: SINCE 1640000000 (Unix timestamp in seconds)
    - Relative: SINCE 1 hour ago, SINCE 30 minutes ago, SINCE 1 day ago
    - Range: SINCE 2 hours ago UNTIL 1 hour ago

    Returns:
    - results: Array of log entries matching the query
    - totalCount: Number of results returned
    - metadata: Query metadata including event types and time window
    """
    try:
        response = await newrelic_logs_service.query_logs(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to query New Relic logs: {str(e)}"
        )


@router.post("/filter", response_model=FilterLogsResponse)
async def filter_logs(
    request: FilterLogsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Filter New Relic logs with common parameters

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Provides a simplified interface for common log filtering
    - Automatically builds NRQL query from parameters
    - Supports text search, time range, and pagination
    - Returns structured log entries

    Use Cases:
    - Simple text search across logs
    - Time-based log filtering
    - Pagination through results

    Parameters:
    - query: Text to search in log messages
    - startTime: Start time in milliseconds since epoch
    - endTime: End time in milliseconds since epoch
    - limit: Maximum number of results (1-1000, default: 100)
    - offset: Pagination offset (default: 0)

    Returns:
    - logs: Array of log entries with timestamp, message, and attributes
    - totalCount: Number of results returned
    - hasMore: Whether more results are available
    """
    try:
        response = await newrelic_logs_service.filter_logs(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to filter New Relic logs: {str(e)}"
        )
