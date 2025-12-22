"""
CloudWatch Metrics API Router
Provides OPEN endpoints for CloudWatch Metrics operations (no authentication)
Designed for RCA bot integration
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from .schemas import (
    ListMetricsRequest,
    ListMetricsResponse,
    GetMetricDataRequest,
    GetMetricDataResponse,
    GetMetricStatisticsRequest,
    GetMetricStatisticsResponse,
    ListMetricStreamsRequest,
    ListMetricStreamsResponse,
    GetMetricStreamRequest,
    GetMetricStreamResponse,
    ListNamespacesResponse,
    DescribeAnomalyDetectorsRequest,
    DescribeAnomalyDetectorsResponse,
)
from .service import cloudwatch_metrics_service

router = APIRouter(prefix="/cloudwatch/metrics", tags=["cloudwatch-metrics"])


@router.post("/list", response_model=ListMetricsResponse)
async def list_metrics(
    request: ListMetricsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    List all available CloudWatch metrics with namespaces and dimensions

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This endpoint helps discover:
    - All metric namespaces (AWS/EC2, AWS/Lambda, AWS/RDS, etc.)
    - Metric names under each namespace
    - Available dimensions (InstanceId, FunctionName, DBInstanceIdentifier, etc.)

    Use cases:
    - Build dropdown lists for metric selection
    - Discover what metrics are available for analysis
    - Find dimension values for filtering

    Example filters:
    - List all EC2 metrics: {"Namespace": "AWS/EC2"}
    - Find CPU metrics: {"MetricName": "CPUUtilization"}
    - Filter by dimension: {"Dimensions": [{"Name": "InstanceId", "Value": "i-12345"}]}

    **Limit**: Maximum number of metrics to return (default: 50, max: 500)
    """
    try:
        response = await cloudwatch_metrics_service.list_metrics(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list metrics: {str(e)}")


@router.get("/namespaces", response_model=ListNamespacesResponse)
async def list_namespaces(
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    List all unique metric namespaces available

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    Returns a simple list of all CloudWatch namespaces available in the account.
    Common namespaces include:
    - AWS/EC2 (EC2 instances)
    - AWS/Lambda (Lambda functions)
    - AWS/RDS (RDS databases)
    - AWS/ELB (Load balancers)
    - AWS/DynamoDB (DynamoDB tables)
    - AWS/S3 (S3 buckets)
    - Custom namespaces (your application metrics)

    Use this to build namespace selector dropdowns in your RCA dashboard.
    """
    try:
        response = await cloudwatch_metrics_service.list_namespaces(
            db=db, workspace_id=workspace_id
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list namespaces: {str(e)}"
        )


@router.post("/data", response_model=GetMetricDataResponse)
async def get_metric_data(
    request: GetMetricDataRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get metric data (time-series) for graphing and analysis

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    This is the PRIMARY endpoint for fetching metric time-series data.
    Use this for:
    - Graphing metrics over time
    - Detecting anomalies and spikes
    - Comparing multiple metrics
    - Math expressions (e.g., SUM, AVG across metrics)
    - Anomaly detection bands

    Features:
    - Query multiple metrics in a single request
    - Support for metric math expressions
    - Automatic aggregation over custom periods
    - Returns timestamps + values arrays for easy plotting

    Example request for CPU utilization:
    ```json
    {
      "MetricDataQueries": [
        {
          "Id": "m1",
          "MetricStat": {
            "Metric": {
              "Namespace": "AWS/EC2",
              "MetricName": "CPUUtilization",
              "Dimensions": [{"Name": "InstanceId", "Value": "i-12345"}]
            },
            "Period": 300,
            "Stat": "Average"
          }
        }
      ],
      "StartTime": 1704067200,
      "EndTime": 1704070800
    }
    ```

    Time format: Unix timestamps in SECONDS (not milliseconds!)
    """
    try:
        response = await cloudwatch_metrics_service.get_metric_data(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get metric data: {str(e)}"
        )


@router.post(
    "/statistics",
    response_model=GetMetricStatisticsResponse,
    response_model_exclude_none=True,
)
async def get_metric_statistics(
    request: GetMetricStatisticsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get metric statistics (simpler alternative to get_metric_data)

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    Use this for simple, single-metric queries when you don't need:
    - Multiple metrics in one request
    - Math expressions
    - Anomaly detection

    Returns aggregated statistics:
    - Average, Sum, Minimum, Maximum, SampleCount
    - Extended statistics (percentiles: p0, p50, p90, p99, p100)

    Example use case:
    - Get average CPU usage for last hour
    - Find max error count in 15-minute periods
    - Calculate p99 latency

    Time format: Unix timestamps in SECONDS
    Period: Granularity in seconds (60, 300, 3600, 86400, etc.)
    """
    try:
        response = await cloudwatch_metrics_service.get_metric_statistics(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get metric statistics: {str(e)}"
        )


@router.post("/streams/list", response_model=ListMetricStreamsResponse)
async def list_metric_streams(
    request: ListMetricStreamsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    List CloudWatch Metric Streams for real-time metric delivery

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    Metric Streams provide near real-time delivery of CloudWatch metrics to:
    - Amazon Kinesis Data Firehose
    - Amazon S3 (via Firehose)
    - Third-party destinations (Datadog, Dynatrace, etc.)

    Use this endpoint to check:
    - Which metric streams are active
    - Stream state (running, stopped)
    - Firehose ARN and S3 destination
    - Last delivery timestamp
    - Any delivery failures

    This is important for RCA because if streams are down,
    your metric data pipeline may be broken.
    """
    try:
        response = await cloudwatch_metrics_service.list_metric_streams(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list metric streams: {str(e)}"
        )


@router.post("/streams/get", response_model=GetMetricStreamResponse)
async def get_metric_stream(
    request: GetMetricStreamRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed information about a specific metric stream

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    Returns comprehensive details about a metric stream:
    - State (running, stopped)
    - Output format (json, opentelemetry0.7)
    - Firehose ARN and destination
    - Include/exclude filters
    - Statistics configurations
    - Last update timestamp

    Use this to troubleshoot metric delivery issues.
    """
    try:
        response = await cloudwatch_metrics_service.get_metric_stream(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get metric stream: {str(e)}"
        )


@router.post("/anomaly-detectors", response_model=DescribeAnomalyDetectorsResponse)
async def describe_anomaly_detectors(
    request: DescribeAnomalyDetectorsRequest,
    workspace_id: str = Query(..., description="Workspace ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Describe CloudWatch anomaly detectors (ML-based anomaly detection)

    **OPEN ENDPOINT - No authentication required (for RCA bot)**

    CloudWatch can use machine learning to automatically detect anomalies
    in your metrics without manual threshold configuration.

    This endpoint returns:
    - Which metrics have anomaly detection enabled
    - Detector state (PENDING_TRAINING, TRAINED_INSUFFICIENT_DATA, TRAINED)
    - Configuration (excluded time ranges, timezone)

    Use cases for RCA:
    - Check if anomaly detection is configured for critical metrics
    - Identify metrics with ML-detected anomalies
    - Verify detector training state

    You can use anomaly detection bands in get_metric_data queries:
    ```json
    {
      "Id": "ad1",
      "Expression": "ANOMALY_DETECTION_BAND(m1, 2)"
    }
    ```
    """
    try:
        response = await cloudwatch_metrics_service.describe_anomaly_detectors(
            db=db, workspace_id=workspace_id, request=request
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to describe anomaly detectors: {str(e)}"
        )
