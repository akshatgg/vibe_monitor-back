"""
CloudWatch Logs API Router
Provides OPEN endpoints for CloudWatch Logs operations (no authentication)
Designed for RCA bot integration
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from .schemas import (
    ListLogGroupsRequest,
    ListLogGroupsResponse,
    ListLogStreamsRequest,
    ListLogStreamsResponse,
    GetLogEventsRequest,
    GetLogEventsResponse,
    StartQueryRequest,
    GetQueryResultsResponse,
    FilterLogEventsRequest,
    FilterLogEventsResponse,
)
from .service import cloudwatch_logs_service

router = APIRouter(prefix="/cloudwatch/logs", tags=["cloudwatch-logs"])


@router.post("/groups", response_model=ListLogGroupsResponse)
async def list_log_groups(
    request: ListLogGroupsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    List CloudWatch log groups for a workspace

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Uses AWS credentials from workspace integration
    - Automatically refreshes expired credentials
    - Supports filtering by log group name prefix
    - Supports pagination with nextToken

    Returns list of log groups with metadata.
    """
    try:
        response = await cloudwatch_logs_service.list_log_groups(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list log groups: {str(e)}"
        )


@router.post("/streams", response_model=ListLogStreamsResponse)
async def list_log_streams(
    request: ListLogStreamsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    List CloudWatch log streams in a log group

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Lists all log streams in the specified log group
    - Supports ordering by LogStreamName or LastEventTime
    - Supports ascending/descending order
    - Supports pagination with nextToken

    Returns list of log streams with timestamps and metadata.
    """
    try:
        response = await cloudwatch_logs_service.list_log_streams(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list log streams: {str(e)}"
        )


@router.post("/events", response_model=GetLogEventsResponse)
async def get_log_events(
    request: GetLogEventsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get log events from a specific log stream

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Retrieves raw log events from a log stream
    - Supports time range filtering (startTime, endTime)
    - Supports forward and backward pagination
    - Can start from head (oldest) or tail (newest)

    Returns log events with timestamps and messages.

    Note: If events array is empty, the log stream may not have logs in the specified time range.
    """
    try:
        response = await cloudwatch_logs_service.get_log_events(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get log events: {str(e)}"
        )


@router.post("/query", response_model=GetQueryResultsResponse)
async def execute_query(
    request: StartQueryRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    max_wait_seconds: int = Query(
        60, description="Maximum seconds to wait for results"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute a CloudWatch Insights query and get results (combined operation)

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint combines start and poll operations into one:
    - Starts the query
    - Automatically polls until results are ready
    - Returns final results when complete
    - No need for separate start/poll requests!

    Query syntax examples:
    - "fields @timestamp, @message | sort @timestamp desc | limit 20"
    - "filter @message like /ERROR/ | stats count() by bin(5m)"
    - "parse @message '[*] *' as level, msg | filter level = 'ERROR'"
    - "filter @type = \"REPORT\" | stats avg(@duration), max(@duration)"

    Time range:
    - startTime and endTime are in SECONDS since epoch (not milliseconds!)
    - Example: for last 1 hour, use: startTime = now - 3600, endTime = now

    Parameters:
    - max_wait_seconds: Maximum time to wait for results (default: 60 seconds)
    - If query takes longer than this, you'll get a timeout error

    Response includes:
    - results: Array of log events matching your query
    - statistics: recordsMatched, recordsScanned, bytesScanned
    - status: Will always be "Complete" (or error)
    """
    try:
        response = await cloudwatch_logs_service.execute_query(
            db=db,
            workspace_id=workspace_id,
            request=request,
            max_wait_seconds=max_wait_seconds,
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to execute query: {str(e)}"
        )


@router.post("/filter", response_model=FilterLogEventsResponse)
async def filter_log_events(
    request: FilterLogEventsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Filter log events across multiple log streams

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Searches across multiple log streams in a log group
    - Supports CloudWatch filter patterns
    - More flexible than get_log_events (which requires specific stream)
    - Supports time range filtering
    - Supports pagination

    Filter pattern examples:
    - "ERROR" - Find logs containing ERROR
    - "[ERROR]" - Find logs with exact word ERROR
    - "[w1=ERROR, w2]" - Extract ERROR and next word
    - "{ $.level = \"error\" }" - JSON filter for level field

    Use cases:
    - Search for errors across all streams
    - Filter by specific keywords or patterns
    - Don't know which stream has the logs

    Returns events with logStreamName included for each event.
    """
    try:
        response = await cloudwatch_logs_service.filter_log_events(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to filter log events: {str(e)}"
        )
