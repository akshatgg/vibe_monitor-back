"""
Datadog Metrics API Router
Provides OPEN endpoints for Datadog Metrics operations (no authentication)
Designed for RCA bot integration
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from .schemas import (
    QueryTimeseriesRequest,
    QueryTimeseriesResponse,
    SimpleQueryRequest,
    SimpleQueryResponse,
    EventsSearchRequest,
    EventsSearchResponse,
    TagsListResponse,
)
from .service import datadog_metrics_service

router = APIRouter(prefix="/datadog/metrics", tags=["datadog-metrics"])


@router.post("/query/timeseries", response_model=QueryTimeseriesResponse)
async def query_timeseries(
    request: QueryTimeseriesRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Query Datadog timeseries metrics data

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint supports TWO formats:

    ## FORMAT 1: Simple (Recommended for RCA Bot - Single Query)
    ```json
    {
      "query": "avg:system.cpu.user{*}",
      "from": 1764608683000,
      "to": 1764608983000
    }
    ```

    ## FORMAT 2: Complex (Multiple Queries with Formulas)
    ```json
    {
      "data": {
        "formula": "a + b",
        "queries": [
          {"data_source": "metrics", "query": "avg:cpu{*}", "name": "a"},
          {"data_source": "metrics", "query": "avg:memory{*}", "name": "b"}
        ]
      },
      "from": 1764608683000,
      "to": 1764608983000
    }
    ```

    Query syntax examples:
    - "avg:system.cpu.user{*}" - Average CPU user time across all hosts
    - "sum:aws.ec2.cpuutilization{*} by {instance-id}" - Sum CPU by instance
    - "avg:custom.api.response_time{service:api}" - Average response time for API service
    - "max:kubernetes.cpu.usage{*}" - Maximum Kubernetes CPU usage

    Formulas (Complex format only):
    - "a" - Return query 'a' as-is
    - "a + b" - Add two queries
    - "a / b" - Divide query 'a' by query 'b'
    - "100 * a / b" - Calculate percentage

    Time range:
    - from and to are in MILLISECONDS since epoch

    Returns:
    - data: Timeseries data with series, timestamps, and values
    - errors: Error message if query failed
    """
    try:
        response = await datadog_metrics_service.query_timeseries(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to query timeseries: {str(e)}"
        )


@router.post("/query", response_model=SimpleQueryResponse)
async def query_simple(
    request: SimpleQueryRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Simplified metrics query with cleaner response format

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This is a simplified version of /query/timeseries that returns a cleaner format.
    Ideal for quick metric viewing and analysis.

    Query examples:
    - "avg:system.cpu.user{*}"
    - "sum:custom.api.requests{service:api}"
    - "max:aws.ec2.cpuutilization{instance-id:i-123}"

    Time range:
    - from_timestamp and to_timestamp are in MILLISECONDS since epoch

    Returns:
    - query: Original query string
    - points: List of {timestamp, value} points
    - totalPoints: Number of data points
    """
    try:
        response = await datadog_metrics_service.query_simple(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to query metrics: {str(e)}"
        )


@router.post("/events/search", response_model=EventsSearchResponse)
async def search_events(
    request: EventsSearchRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Search Datadog events (deployments, alerts, changes, annotations)

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint searches for events that occurred during a time range.
    Events show what changed in your infrastructure - critical for RCA!

    Event types include:
    - Deployments
    - Alerts fired/resolved
    - Configuration changes
    - Auto-scaling events
    - Host/container lifecycle events
    - Custom annotations

    Time range:
    - start and end are in SECONDS since epoch (not milliseconds!)

    Filters (optional):
    - tags: Comma-separated tags (e.g., 'env:prod,service:api')

    Example request:
    ```json
    {
      "start": 1764608683,
      "end": 1764608983,
      "tags": "env:prod,service:api"
    }
    ```

    Note: Events are always returned unaggregated (detailed) for RCA analysis

    Returns:
    - events: List of events with details (title, text, timestamp, source, tags, etc.)
    - totalCount: Number of events found

    RCA Use Case:
    Query events around error time to see what changed (deployments, config, alerts)
    """
    try:
        response = await datadog_metrics_service.search_events(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to search events: {str(e)}"
        )


@router.get("/tags/list", response_model=TagsListResponse)
async def list_tags(
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    List all available Datadog tags

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint discovers tags by sampling recent events (last 7 days).
    Helps RCA bot know what tags are available for filtering events/metrics.

    How it works:
    - Queries recent events from last 7 days
    - Extracts all unique tags from those events
    - Organizes tags by category (env, service, region, etc.)

    Returns:
    - tags: List of all tags (e.g., ["env:prod", "service:api", "region:us-east-1"])
    - tagsByCategory: Tags organized by category
      {
        "env": ["prod", "staging", "dev"],
        "service": ["api", "db", "frontend"],
        "region": ["us-east-1", "us-west-2"]
      }
    - totalTags: Total number of unique tags

    RCA Bot Use Case:
    1. Call this endpoint first to discover available tags
    2. Use discovered tags to filter events/metrics queries

    Example:
    Bot discovers: "service" tags = ["api", "db", "frontend"]
    User: "API is failing"
    Bot: Queries events with tags="env:prod,service:api"

    Note: Tags are extracted from recent events, so only actively used tags are returned
    """
    try:
        response = await datadog_metrics_service.list_tags(
            db=db, workspace_id=workspace_id
        )
        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list tags: {str(e)}")
