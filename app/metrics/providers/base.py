"""
Abstract base class for metrics providers
"""
from abc import ABC, abstractmethod
from typing import List, Optional

from ..models import (
    InstantMetricResponse,
    RangeMetricResponse,
    TargetsResponse,
    MetricQueryParams,
    TimeRange
)


class BaseMetricsProvider(ABC):
    """Abstract base class for metrics providers"""

    def __init__(self, base_url: str, **kwargs):
        self.base_url = base_url
        self.config = kwargs

    @abstractmethod
    async def get_instant_metrics(
        self,
        metric_name: str,
        params: Optional[MetricQueryParams] = None
    ) -> InstantMetricResponse:
        """
        Get instant metric values

        Args:
            metric_name: Name of the metric to query
            params: Query parameters including service_name, labels, etc.

        Returns:
            InstantMetricResponse with current metric values
        """
        pass

    @abstractmethod
    async def get_range_metrics(
        self,
        metric_name: str,
        time_range: TimeRange,
        params: Optional[MetricQueryParams] = None
    ) -> RangeMetricResponse:
        """
        Get metric values over a time range

        Args:
            metric_name: Name of the metric to query
            time_range: Time range specification
            params: Query parameters including service_name, labels, etc.

        Returns:
            RangeMetricResponse with time series data
        """
        pass

    @abstractmethod
    async def get_cpu_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get CPU usage metrics"""
        pass

    @abstractmethod
    async def get_memory_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get memory usage metrics"""
        pass

    @abstractmethod
    async def get_http_request_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get HTTP request rate metrics"""
        pass

    @abstractmethod
    async def get_http_latency_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None,
        percentile: float = 0.95
    ) -> RangeMetricResponse:
        """Get HTTP request latency metrics"""
        pass

    @abstractmethod
    async def get_error_rate_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get error rate metrics"""
        pass

    @abstractmethod
    async def get_throughput_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get throughput metrics"""
        pass

    @abstractmethod
    async def get_availability_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get service availability metrics"""
        pass

    @abstractmethod
    async def get_all_metric_names(self) -> List[str]:
        """Get list of all available metric names"""
        pass

    @abstractmethod
    async def get_targets_status(self) -> TargetsResponse:
        """Get monitoring targets status"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the metrics provider is healthy"""
        pass