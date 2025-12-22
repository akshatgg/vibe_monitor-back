"""
Pydantic schemas for CloudWatch Metrics API
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


# ===== List Metrics Schemas =====


class DimensionFilter(BaseModel):
    """Dimension filter for metrics"""

    Name: str = Field(..., description="Dimension name")
    Value: Optional[str] = Field(
        None, description="Dimension value (optional for wildcard)"
    )


class MetricInfo(BaseModel):
    """Schema for a single metric"""

    Namespace: Optional[str] = Field(
        None, description="Metric namespace (e.g., AWS/EC2, AWS/Lambda)"
    )
    MetricName: Optional[str] = Field(None, description="Metric name")
    Dimensions: Optional[List[Dict[str, str]]] = Field(
        None, description="Metric dimensions"
    )


class ListMetricsRequest(BaseModel):
    """Request schema for listing metrics"""

    Namespace: Optional[str] = Field(
        None, description="Filter by namespace (e.g., AWS/EC2)"
    )
    MetricName: Optional[str] = Field(None, description="Filter by metric name")
    Dimensions: Optional[List[DimensionFilter]] = Field(
        None, description="Filter by dimensions"
    )
    Limit: Optional[int] = Field(
        50, description="Maximum number of metrics to return (default: 50)"
    )


class ListMetricsResponse(BaseModel):
    """Response schema for listing metrics"""

    Metrics: List[MetricInfo] = Field(..., description="List of metrics")
    TotalCount: int = Field(..., description="Total number of metrics returned")


# ===== Get Metric Data Schemas =====


class MetricDimension(BaseModel):
    """Dimension for a metric"""

    Name: str = Field(..., description="Dimension name (e.g., InstanceId, Service)")
    Value: str = Field(..., description="Dimension value (e.g., i-1234567, API)")


class MetricSpecification(BaseModel):
    """Metric specification"""

    Namespace: str = Field(
        ..., description="Metric namespace (e.g., AWS/EC2, VibeMonitor/TestMetrics)"
    )
    MetricName: str = Field(
        ..., description="Metric name (e.g., CPUUtilization, APIResponseTime)"
    )
    Dimensions: Optional[List[MetricDimension]] = Field(
        None, description="Metric dimensions for filtering"
    )


class MetricStat(BaseModel):
    """Metric stat configuration"""

    Metric: MetricSpecification = Field(
        ..., description="Metric specification with Namespace, MetricName, Dimensions"
    )
    Period: int = Field(..., description="Period in seconds (60, 300, 3600, etc.)")
    Stat: str = Field(
        ..., description="Statistic: Average, Sum, Minimum, Maximum, SampleCount"
    )


class MetricDataQuery(BaseModel):
    """Metric data query"""

    model_config = ConfigDict(populate_by_name=True)

    Id: str = Field(..., description="Unique ID for this query (e.g., 'm1', 'e1')")
    metric_stat: Optional[MetricStat] = Field(
        None, description="Metric stat configuration", alias="MetricStat"
    )


class GetMetricDataRequest(BaseModel):
    """Request schema for getting metric data (time-series)"""

    MetricDataQueries: List[MetricDataQuery] = Field(
        ..., description="List of metric queries"
    )
    StartTime: int = Field(..., description="Start time (Unix timestamp in seconds)")
    EndTime: int = Field(..., description="End time (Unix timestamp in seconds)")
    ScanBy: Optional[str] = Field(
        "TimestampDescending",
        description="Scan order: TimestampAscending or TimestampDescending",
    )
    MaxDatapoints: Optional[int] = Field(
        50, description="Max datapoints to return (default: 50)"
    )


class MetricDataResult(BaseModel):
    """Result for a single metric query"""

    Id: str = Field(..., description="Query ID")
    Label: Optional[str] = Field(None, description="Metric label")
    Timestamps: List[datetime] = Field(..., description="Timestamps for data points")
    Values: List[float] = Field(..., description="Values for data points")
    StatusCode: Optional[str] = Field(
        None, description="Status code: Complete, InternalError, PartialData"
    )
    Messages: Optional[List[Dict[str, str]]] = Field(
        None, description="Status messages"
    )


class GetMetricDataResponse(BaseModel):
    """Response schema for getting metric data"""

    MetricDataResults: List[MetricDataResult] = Field(
        ..., description="Metric data results"
    )
    Messages: Optional[List[Dict[str, str]]] = Field(
        None, description="Response messages"
    )


# ===== Get Metric Statistics Schemas =====


class Dimension(BaseModel):
    """Dimension key-value pair"""

    Name: str = Field(..., description="Dimension name")
    Value: str = Field(..., description="Dimension value")


class GetMetricStatisticsRequest(BaseModel):
    """Request schema for getting metric statistics"""

    Namespace: str = Field(..., description="Metric namespace (e.g., AWS/EC2)")
    MetricName: str = Field(..., description="Metric name (e.g., CPUUtilization)")
    Dimensions: Optional[List[Dimension]] = Field(None, description="Metric dimensions")
    StartTime: int = Field(..., description="Start time (Unix timestamp in seconds)")
    EndTime: int = Field(..., description="End time (Unix timestamp in seconds)")
    Period: int = Field(300, description="Period in seconds (minimum 60)")
    Statistics: Optional[List[str]] = Field(
        None, description="Statistics: Average, Sum, Minimum, Maximum, SampleCount"
    )
    ExtendedStatistics: Optional[List[str]] = Field(
        None, description="Percentiles: p0.0, p10, p50, p90, p99, p100"
    )
    MaxDatapoints: Optional[int] = Field(
        50, description="Max datapoints to return (default: 50)"
    )


class Datapoint(BaseModel):
    """Single datapoint in metric statistics"""

    model_config = ConfigDict(exclude_none=True)

    Timestamp: datetime = Field(..., description="Datapoint timestamp")
    Average: Optional[float] = Field(None, description="Average value")
    Sum: Optional[float] = Field(None, description="Sum value")
    Minimum: Optional[float] = Field(None, description="Minimum value")
    Maximum: Optional[float] = Field(None, description="Maximum value")
    SampleCount: Optional[float] = Field(None, description="Sample count")
    Unit: Optional[str] = Field(None, description="Unit")
    ExtendedStatistics: Optional[Dict[str, float]] = Field(
        None, description="Extended statistics (percentiles)"
    )


class GetMetricStatisticsResponse(BaseModel):
    """Response schema for getting metric statistics"""

    model_config = ConfigDict(exclude_none=True)

    Label: str = Field(..., description="Metric label")
    Datapoints: List[Datapoint] = Field(..., description="Data points")
    TotalDatapoints: int = Field(..., description="Total number of datapoints returned")


# ===== List Metric Streams Schemas =====


class MetricStreamFilter(BaseModel):
    """Metric stream namespace filter"""

    Namespace: str = Field(..., description="Namespace to include/exclude")
    MetricNames: Optional[List[str]] = Field(
        None, description="Metric names within namespace"
    )


class MetricStreamStatisticsConfiguration(BaseModel):
    """Statistics configuration for metric stream"""

    IncludeMetrics: List[Dict[str, Any]] = Field(..., description="Metrics to include")
    AdditionalStatistics: List[str] = Field(..., description="Additional statistics")


class MetricStreamInfo(BaseModel):
    """Metric stream information"""

    Arn: str = Field(..., description="Stream ARN")
    CreationDate: datetime = Field(..., description="Creation timestamp")
    LastUpdateDate: datetime = Field(..., description="Last update timestamp")
    Name: str = Field(..., description="Stream name")
    FirehoseArn: str = Field(..., description="Firehose delivery stream ARN")
    State: str = Field(..., description="Stream state: running, stopped")
    OutputFormat: str = Field(..., description="Output format: json, opentelemetry0.7")
    IncludeFilters: Optional[List[MetricStreamFilter]] = Field(
        None, description="Include filters"
    )
    ExcludeFilters: Optional[List[MetricStreamFilter]] = Field(
        None, description="Exclude filters"
    )
    StatisticsConfigurations: Optional[List[MetricStreamStatisticsConfiguration]] = (
        Field(None, description="Statistics configurations")
    )


class ListMetricStreamsRequest(BaseModel):
    """Request schema for listing metric streams"""

    Limit: Optional[int] = Field(
        50, description="Maximum number of streams to return (default: 50)"
    )


class ListMetricStreamsResponse(BaseModel):
    """Response schema for listing metric streams"""

    Entries: List[MetricStreamInfo] = Field(..., description="Metric streams")
    TotalCount: int = Field(..., description="Total number of streams returned")


# ===== Get Metric Stream Schemas =====


class GetMetricStreamRequest(BaseModel):
    """Request schema for getting metric stream details"""

    Name: str = Field(..., description="Metric stream name")


class GetMetricStreamResponse(BaseModel):
    """Response schema for getting metric stream details"""

    Arn: Optional[str] = Field(None, description="Stream ARN")
    Name: Optional[str] = Field(None, description="Stream name")
    FirehoseArn: Optional[str] = Field(None, description="Firehose ARN")
    State: Optional[str] = Field(None, description="Stream state")
    CreationDate: Optional[datetime] = Field(None, description="Creation date")
    LastUpdateDate: Optional[datetime] = Field(None, description="Last update date")
    OutputFormat: Optional[str] = Field(None, description="Output format")
    IncludeFilters: Optional[List[MetricStreamFilter]] = Field(
        None, description="Include filters"
    )
    ExcludeFilters: Optional[List[MetricStreamFilter]] = Field(
        None, description="Exclude filters"
    )
    StatisticsConfigurations: Optional[List[MetricStreamStatisticsConfiguration]] = (
        Field(None, description="Statistics configurations")
    )


# ===== List Namespaces (Custom Helper) =====


class ListNamespacesResponse(BaseModel):
    """Response schema for listing unique namespaces"""

    Namespaces: List[str] = Field(..., description="List of unique namespaces")


# ===== Anomaly Detection =====


class AnomalyDetectorConfiguration(BaseModel):
    """Anomaly detector configuration"""

    ExcludedTimeRanges: Optional[List[Dict[str, datetime]]] = Field(
        None, description="Excluded time ranges"
    )
    MetricTimezone: Optional[str] = Field(None, description="Metric timezone")


class DescribeAnomalyDetectorsRequest(BaseModel):
    """Request schema for describing anomaly detectors"""

    Namespace: Optional[str] = Field(None, description="Metric namespace")
    MetricName: Optional[str] = Field(None, description="Metric name")
    Dimensions: Optional[List[Dimension]] = Field(None, description="Dimensions")
    Limit: Optional[int] = Field(
        50, description="Maximum number of detectors to return (default: 50)"
    )


class AnomalyDetector(BaseModel):
    """Anomaly detector information"""

    Namespace: Optional[str] = Field(None, description="Namespace")
    MetricName: Optional[str] = Field(None, description="Metric name")
    Dimensions: Optional[List[Dimension]] = Field(None, description="Dimensions")
    Stat: Optional[str] = Field(None, description="Statistic")
    Configuration: Optional[AnomalyDetectorConfiguration] = Field(
        None, description="Configuration"
    )
    StateValue: Optional[str] = Field(
        None, description="State: PENDING_TRAINING, TRAINED_INSUFFICIENT_DATA, TRAINED"
    )


class DescribeAnomalyDetectorsResponse(BaseModel):
    """Response schema for anomaly detectors"""

    AnomalyDetectors: List[AnomalyDetector] = Field(
        ..., description="Anomaly detectors"
    )
    TotalCount: int = Field(..., description="Total number of detectors returned")
