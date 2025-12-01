"""
New Relic Metrics API Router
Provides OPEN endpoints for New Relic Metrics operations (no authentication)
Designed for RCA bot integration and testing
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from .schemas import (
    QueryMetricsRequest,
    QueryMetricsResponse,
    GetTimeSeriesRequest,
    GetTimeSeriesResponse,
    GetInfraMetricsRequest,
    GetInfraMetricsResponse,
)
from .service import newrelic_metrics_service

router = APIRouter(prefix="/newrelic/metrics", tags=["newrelic-metrics"])


@router.post("/query", response_model=QueryMetricsResponse)
async def query_metrics(
    request: QueryMetricsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Query New Relic metrics using NRQL

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Executes NRQL queries against New Relic for metrics
    - Uses workspace's stored New Relic credentials
    - Supports full NRQL syntax for metrics, transactions, and custom events
    - Returns aggregated metric data

    NRQL Query Examples:
    - "SELECT average(duration) FROM Transaction WHERE appName = 'my-app' SINCE 1 hour ago"
    - "SELECT count(*) FROM Transaction WHERE httpResponseCode = 500 FACET appName SINCE 1 day ago"
    - "SELECT percentile(duration, 95, 99) FROM Transaction SINCE 1 hour ago TIMESERIES"
    - "SELECT rate(count(*), 1 minute) FROM Transaction WHERE appName = 'api' SINCE 30 minutes ago"

    Metric Aggregations:
    - average(), min(), max(), sum(), count()
    - percentile(attribute, 50, 95, 99)
    - rate(count(*), 1 minute)
    - apdex(duration)
    - percentage(count(*), WHERE condition)

    Time Syntax:
    - Absolute: SINCE 1640000000 (Unix timestamp in seconds)
    - Relative: SINCE 1 hour ago, SINCE 30 minutes ago, SINCE 1 day ago
    - Range: SINCE 2 hours ago UNTIL 1 hour ago
    - TIMESERIES: Add for time series data (TIMESERIES AUTO or TIMESERIES 5 minutes)

    Returns:
    - results: Array of metric data points
    - totalCount: Number of results returned
    - metadata: Query metadata including event types and time window
    """
    try:
        response = await newrelic_metrics_service.query_metrics(
            db=db,
            workspace_id=workspace_id,
            request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query New Relic metrics: {str(e)}"
        )


@router.post("/timeseries", response_model=GetTimeSeriesResponse)
async def get_time_series(
    request: GetTimeSeriesRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get time series metrics data

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Retrieves time series data for a specific metric
    - Supports multiple aggregation functions
    - Automatically formats data as time series

    Use Cases:
    - Monitor metric trends over time
    - Visualize metric changes

    Parameters:
    - metric_name: Name of the metric to query
    - startTime: Start time in seconds since epoch (required)
    - endTime: End time in seconds since epoch (required)
    - aggregation: Function to aggregate (average, sum, min, max, count)
    - timeseries: Return as time series (default: true)
    - where_clause: Optional filter (e.g., "appName = 'my-app'")

    Returns:
    - metricName: The queried metric name
    - dataPoints: Array of time series data points with timestamps and values
    - aggregation: Aggregation function used
    - totalCount: Number of data points
    """
    try:
        response = await newrelic_metrics_service.get_time_series(
            db=db,
            workspace_id=workspace_id,
            request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get time series metrics: {str(e)}"
        )


@router.post("/infrastructure", response_model=GetInfraMetricsResponse)
async def get_infra_metrics(
    request: GetInfraMetricsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get infrastructure monitoring metrics

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint:
    - Retrieves infrastructure metrics from New Relic Infrastructure
    - Supports system-level metrics (CPU, memory, disk, network)
    - Can filter by specific hostname
    - Returns time series data

    Common Infrastructure Metrics:
    - cpuPercent: CPU utilization percentage
    - memoryUsedPercent: Memory utilization percentage
    - diskUsedPercent: Disk utilization percentage
    - loadAverageOneMinute: 1-minute load average
    - networkReceiveBytesPerSecond: Network receive throughput
    - networkTransmitBytesPerSecond: Network transmit throughput

    Parameters:
    - metric_name: Infrastructure metric name (e.g., 'cpuPercent')
    - hostname: Optional filter by hostname
    - startTime: Start time in seconds since epoch (required)
    - endTime: End time in seconds since epoch (required)
    - aggregation: Function to aggregate (average, sum, min, max)

    Returns:
    - metricName: Infrastructure metric name queried
    - dataPoints: Array of metric data points over time
    - aggregation: Aggregation function used
    - totalCount: Number of data points
    """
    try:
        response = await newrelic_metrics_service.get_infra_metrics(
            db=db,
            workspace_id=workspace_id,
            request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get infrastructure metrics: {str(e)}"
        )


