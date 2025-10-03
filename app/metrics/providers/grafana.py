"""
Grafana metrics provider implementation
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from .base import BaseMetricsProvider
from ..models import (
    InstantMetricResponse,
    RangeMetricResponse,
    TargetsResponse,
    MetricQueryParams,
    MetricTarget,
    MetricSeries,
    MetricValue,
    TimeRange
)

logger = logging.getLogger(__name__)


class GrafanaProvider(BaseMetricsProvider):
    """Grafana metrics provider implementation using Prometheus data source via Grafana datasource proxy"""

    def __init__(self, base_url: str = "http://localhost:3000", **kwargs):
        super().__init__(base_url, **kwargs)
        self.api_key = kwargs.get("api_key")
        self.username = kwargs.get("username")
        self.password = kwargs.get("password")
        self.datasource_uid = kwargs.get("datasource_uid", "prometheus")

        # Configure httpx client with basic auth if username/password provided
        auth = None
        if self.username and self.password:
            auth = (self.username, self.password)

        self.client = httpx.AsyncClient(timeout=30.0, auth=auth)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Grafana API requests"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _format_time(self, time_value) -> int:
        """Format time value for Grafana API (milliseconds since epoch)"""
        if isinstance(time_value, datetime):
            return int(time_value.timestamp() * 1000)

        # Handle relative time strings like "now-5m", "now-1h"
        if isinstance(time_value, str):
            if time_value == "now":
                return int(datetime.now(timezone.utc).timestamp() * 1000)
            elif time_value.startswith("now-"):
                from datetime import timedelta
                import re

                # Parse relative time like "now-5m", "now-1h", "now-1d"
                match = re.match(r'now-(\d+)([smhd])', time_value)
                if match:
                    amount, unit = match.groups()
                    amount = int(amount)

                    if unit == 's':
                        delta = timedelta(seconds=amount)
                    elif unit == 'm':
                        delta = timedelta(minutes=amount)
                    elif unit == 'h':
                        delta = timedelta(hours=amount)
                    elif unit == 'd':
                        delta = timedelta(days=amount)
                    else:
                        return int(datetime.now(timezone.utc).timestamp() * 1000)

                    target_time = datetime.now(timezone.utc) - delta
                    return int(target_time.timestamp() * 1000)

        return int(time_value)

    def _build_label_filter(
        self,
        service_name: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Build label filter string for PromQL

        Supports multiple common service label names:
        - job (standard Prometheus convention)
        - service (alternative naming)
        - service_name (explicit naming)

        Uses exact match for job, with fallback support for other label names
        """
        label_filters = []

        if service_name:
            # Primary: Use 'job' as standard Prometheus label
            label_filters.append(f'job="{service_name}"')

        if labels:
            for key, value in labels.items():
                label_filters.append(f'{key}="{value}"')

        if label_filters:
            return '{' + ','.join(label_filters) + '}'
        return ""

    def _build_promql_query(
        self,
        base_metric: str,
        service_name: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        aggregation: Optional[str] = None
    ) -> str:
        """Build PromQL query with optional filters - for simple metrics only"""
        label_filter = self._build_label_filter(service_name, labels)
        metric_query = f"{base_metric}{label_filter}"

        if aggregation:
            metric_query = f"{aggregation}({metric_query})"

        return metric_query

    async def _query_grafana(self, promql_query: str, start_time: int, end_time: int, step: str = "60s") -> Dict[str, Any]:
        """Query Prometheus via Grafana datasource proxy API"""
        # Use Grafana's datasource proxy to query Prometheus
        url = urljoin(self.base_url, f"/api/datasources/proxy/uid/{self.datasource_uid}/api/v1/query_range")

        payload = {
            "query": promql_query,
            "start": int(start_time / 1000),  # Convert milliseconds to seconds
            "end": int(end_time / 1000),
            "step": step
        }

        headers = self._get_headers()
        logger.debug(f"Querying Grafana datasource proxy: {url} with query: {promql_query}")

        try:
            response = await self.client.get(url, params=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Request error to Grafana: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Grafana: {e.response.status_code} - {e.response.text}")
            raise

    async def _query_instant(self, promql_query: str) -> Dict[str, Any]:
        """Query Prometheus via Grafana datasource proxy for instant metrics"""
        url = urljoin(self.base_url, f"/api/datasources/proxy/uid/{self.datasource_uid}/api/v1/query")

        payload = {"query": promql_query}

        headers = self._get_headers()
        logger.debug(f"Querying Grafana datasource proxy (instant): {url} with query: {promql_query}")

        try:
            response = await self.client.get(url, params=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Request error to Grafana: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Grafana: {e.response.status_code} - {e.response.text}")
            raise

    async def get_instant_metrics(
        self,
        metric_name: str,
        params: Optional[MetricQueryParams] = None
    ) -> InstantMetricResponse:
        """Get instant metric values from Grafana"""
        query_params = params or MetricQueryParams()

        promql_query = self._build_promql_query(
            metric_name,
            service_name=query_params.service_name,
            labels=query_params.labels
        )

        response_data = await self._query_instant(promql_query)

        return InstantMetricResponse(
            status=response_data.get("status", "error"),
            data=response_data.get("data", {}),
            metric_name=metric_name,
            result_type=response_data.get("data", {}).get("resultType", ""),
            result=response_data.get("data", {}).get("result", [])
        )

    async def get_range_metrics(
        self,
        metric_name: str,
        time_range: TimeRange,
        params: Optional[MetricQueryParams] = None
    ) -> RangeMetricResponse:
        """Get metric values over a time range from Grafana"""
        query_params = params or MetricQueryParams()

        promql_query = self._build_promql_query(
            metric_name,
            service_name=query_params.service_name,
            labels=query_params.labels
        )

        start_time = self._format_time(time_range.start)
        end_time = self._format_time(time_range.end)

        response_data = await self._query_grafana(promql_query, start_time, end_time, time_range.step)

        # Parse result into MetricSeries objects
        result_data = response_data.get("data", {}).get("result", [])
        parsed_results = []

        for series in result_data:
            values = []
            for timestamp, value in series.get("values", []):
                values.append(MetricValue(
                    timestamp=datetime.fromtimestamp(float(timestamp), tz=timezone.utc),
                    value=float(value)
                ))

            parsed_results.append(MetricSeries(
                metric=series.get("metric", {}),
                values=values
            ))

        return RangeMetricResponse(
            status=response_data.get("status", "error"),
            data=response_data.get("data", {}),
            metric_name=metric_name,
            result_type=response_data.get("data", {}).get("resultType", "matrix"),
            result=parsed_results
        )

    async def get_cpu_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get CPU usage metrics"""
        label_filter = self._build_label_filter(service_name=service_name)
        query = f"rate(process_cpu_seconds_total{label_filter}[5m]) * 100"

        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        # Pass empty params since filter already in query
        params = MetricQueryParams()
        return await self.get_range_metrics(query, time_range, params)

    async def get_memory_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get memory usage metrics"""
        label_filter = self._build_label_filter(service_name=service_name)
        query = f"process_resident_memory_bytes{label_filter} / 1024 / 1024"  # Convert to MB

        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        params = MetricQueryParams()
        return await self.get_range_metrics(query, time_range, params)

    async def get_http_request_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get HTTP request rate metrics"""
        label_filter = self._build_label_filter(service_name=service_name)
        query = f"rate(http_requests_total{label_filter}[5m])"

        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        params = MetricQueryParams()
        return await self.get_range_metrics(query, time_range, params)

    async def get_http_latency_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None,
        percentile: float = 0.95
    ) -> RangeMetricResponse:
        """Get HTTP request latency metrics"""
        label_filter = self._build_label_filter(service_name=service_name)
        query = f"histogram_quantile({percentile}, rate(http_request_duration_seconds_bucket{label_filter}[5m]))"

        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        params = MetricQueryParams()
        return await self.get_range_metrics(query, time_range, params)

    async def get_error_rate_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get error rate metrics"""
        # Build label filter with service_name and status filter
        if service_name:
            # Combine status filter with service filter
            query = f'rate(http_requests_total{{status=~"5..",job="{service_name}"}}[5m])'
        else:
            # Status filter only
            query = 'rate(http_requests_total{status=~"5.."}[5m])'

        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        params = MetricQueryParams()
        return await self.get_range_metrics(query, time_range, params)

    async def get_throughput_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get throughput metrics"""
        label_filter = self._build_label_filter(service_name=service_name)
        # Group by job to maintain consistency with service_name filtering
        if service_name:
            # If filtering by service, group by job
            query = f"sum(rate(http_requests_total{label_filter}[5m])) by (job)"
        else:
            # If no filter, group by job to show all services
            query = "sum(rate(http_requests_total[5m])) by (job)"

        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        params = MetricQueryParams()
        return await self.get_range_metrics(query, time_range, params)

    async def get_availability_metrics(
        self,
        service_name: Optional[str] = None,
        time_range: Optional[TimeRange] = None
    ) -> RangeMetricResponse:
        """Get service availability metrics"""
        label_filter = self._build_label_filter(service_name=service_name)
        query = f"up{label_filter}"

        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        params = MetricQueryParams()
        return await self.get_range_metrics(query, time_range, params)

    async def get_all_metric_names(self) -> List[str]:
        """Get list of all available metric names via Grafana datasource proxy"""
        url = urljoin(self.base_url, f"/api/datasources/proxy/uid/{self.datasource_uid}/api/v1/label/__name__/values")

        headers = self._get_headers()
        try:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            response_data = response.json()

            if response_data.get("status") == "success":
                return response_data.get("data", [])
            else:
                logger.error(f"Failed to get metric names: {response_data}")
                return []
        except Exception as e:
            logger.error(f"Error getting metric names: {e}")
            return []

    async def get_targets_status(self) -> TargetsResponse:
        """Get monitoring targets status via Grafana datasource proxy"""
        url = urljoin(self.base_url, f"/api/datasources/proxy/uid/{self.datasource_uid}/api/v1/targets")

        headers = self._get_headers()
        try:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            response_data = response.json()

            # Parse targets data
            targets_data = response_data.get("data", {})
            parsed_targets = {}

            for target_type, targets_list in targets_data.items():
                parsed_targets[target_type] = []
                for target in targets_list:
                    try:
                        parsed_target = MetricTarget(
                            discoveredLabels=target.get("discoveredLabels", {}),
                            labels=target.get("labels", {}),
                            scrapePool=target.get("scrapePool", ""),
                            scrapeUrl=target.get("scrapeUrl", ""),
                            globalUrl=target.get("globalUrl", ""),
                            lastError=target.get("lastError"),
                            lastScrape=datetime.fromisoformat(target.get("lastScrape", "").replace("Z", "+00:00")),
                            lastScrapeDuration=float(target.get("lastScrapeDuration", 0)),
                            health=target.get("health", "unknown")
                        )
                        parsed_targets[target_type].append(parsed_target)
                    except Exception as e:
                        logger.warning(f"Failed to parse target data: {e}")
                        continue

            return TargetsResponse(
                status=response_data.get("status", "error"),
                data=parsed_targets
            )
        except Exception as e:
            logger.error(f"Error getting targets status: {e}")
            return TargetsResponse(status="error", data={})

    async def health_check(self) -> bool:
        """Check if Grafana datasource proxy is healthy"""
        try:
            url = urljoin(self.base_url, f"/api/datasources/proxy/uid/{self.datasource_uid}/api/v1/query")
            headers = self._get_headers()
            response = await self.client.get(url, params={"query": "up"}, headers=headers)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Grafana health check failed: {e}")
            return False