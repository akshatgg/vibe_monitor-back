"""
Metrics service layer for business logic
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import re

from sqlalchemy import select
import httpx

from ..core.database import AsyncSessionLocal
from ..models import GrafanaIntegration
from .models import (
    InstantMetricResponse,
    RangeMetricResponse,
    TargetsResponse,
    MetricQueryParams,
    MetricTarget,
    MetricSeries,
    MetricValue,
    TimeRange,
    LabelResponse
)
from .utils import get_prometheus_uid_cached

logger = logging.getLogger(__name__)


class MetricsService:
    """Service layer for metrics operations - Direct Grafana integration"""

    async def _get_workspace_config(self, workspace_id: str) -> tuple[str, str, str]:
        """Get Grafana config for a specific workspace from database"""
        # Fetch from database
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(GrafanaIntegration).where(
                    GrafanaIntegration.vm_workspace_id == workspace_id
                )
            )
            integration = result.scalar_one_or_none()

            if not integration:
                raise ValueError(f"No Grafana configuration found for workspace {workspace_id}")

            # Auto-discover Prometheus UID from Grafana
            datasource_uid = await get_prometheus_uid_cached(
                grafana_url=integration.grafana_url,
                api_token=integration.api_token
            )
            logger.info(f"Auto-discovered Prometheus UID for workspace {workspace_id}: {datasource_uid}")

            return integration.grafana_url, integration.api_token, datasource_uid

    def _escape_promql_value(self, value: str) -> str:
        """
        Escape special characters in PromQL label values.
        Prevents PromQL injection attacks.
        """
        if not value:
            return value
        # Escape backslashes first, then quotes
        return value.replace('\\', '\\\\').replace('"', '\\"')

    def _get_headers(self, api_token: str) -> Dict[str, str]:
        """Get headers for Grafana API requests"""
        headers = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        return headers

    def _format_time(self, time_value) -> int:
        """
        Format time value for Grafana API (milliseconds since epoch)

        Args:
            time_value: datetime object, int/float timestamp, or time string
                       ("now", "now-5m", or numeric string)

        Returns:
            int: Timestamp in milliseconds since epoch

        Raises:
            ValueError: If time_value cannot be converted to a valid timestamp
        """
        if isinstance(time_value, datetime):
            return int(time_value.timestamp() * 1000)

        # Handle relative time strings like "now-5m", "now-1h"
        if isinstance(time_value, str):
            if time_value == "now":
                return int(datetime.now(timezone.utc).timestamp() * 1000)
            elif time_value.startswith("now-"):
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

        # Handle numeric values (int, float, or numeric strings)
        if isinstance(time_value, (int, float)):
            return int(time_value)

        # Attempt to convert numeric strings
        try:
            # Try to parse as float first (handles "123.45" and "123")
            return int(float(time_value))
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid time_value: {time_value!r}. Expected datetime, "
                f"int/float timestamp, 'now', 'now-Xu' (X=number, u=s/m/h/d), "
                f"or numeric string."
            ) from e

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
            # Escape service_name to prevent PromQL injection
            escaped_service = self._escape_promql_value(service_name)
            label_filters.append(f'job="{escaped_service}"')

        if labels:
            for key, value in labels.items():
                # Escape both key and value to prevent PromQL injection
                escaped_key = self._escape_promql_value(key)
                escaped_value = self._escape_promql_value(value)
                label_filters.append(f'{escaped_key}="{escaped_value}"')

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

    async def _query_grafana(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_token: str,
        datasource_uid: str,
        promql_query: str,
        start_time: int,
        end_time: int,
        step: str = "60s",
        workspace_id: str = None,
        retry_on_auth_error: bool = True
    ) -> Dict[str, Any]:
        """Query Prometheus via Grafana datasource proxy API"""
        # Use Grafana's datasource proxy to query Prometheus
        # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
        url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/api/v1/query_range"

        payload = {
            "query": promql_query,
            "start": int(start_time / 1000),  # Convert milliseconds to seconds
            "end": int(end_time / 1000),
            "step": step
        }

        headers = self._get_headers(api_token)
        logger.debug(f"Querying Grafana datasource proxy: {url} with query: {promql_query}")

        try:
            response = await client.get(url, params=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Request error to Grafana: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Grafana: {e.response.status_code} - {e.response.text}")
            raise

    async def _query_instant(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_token: str,
        datasource_uid: str,
        promql_query: str,
        workspace_id: str = None,
        retry_on_auth_error: bool = True
    ) -> Dict[str, Any]:
        """Query Prometheus via Grafana datasource proxy for instant metrics"""
        # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
        url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/api/v1/query"

        payload = {"query": promql_query}

        headers = self._get_headers(api_token)
        logger.debug(f"Querying Grafana datasource proxy (instant): {url} with query: {promql_query}")

        try:
            response = await client.get(url, params=payload, headers=headers)
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
        workspace_id: str,
        service_name: str = None,
        labels: dict = None,
        timeout: str = None
    ) -> InstantMetricResponse:
        """Get instant metric values"""
        base_url, api_token, datasource_uid = await self._get_workspace_config(workspace_id)

        promql_query = self._build_promql_query(
            metric_name,
            service_name=service_name,
            labels=labels
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response_data = await self._query_instant(
                client, base_url, api_token, datasource_uid, promql_query,
                workspace_id=workspace_id
            )

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
        workspace_id: str,
        service_name: str = None,
        labels: dict = None,
        timeout: str = None
    ) -> RangeMetricResponse:
        """Get metric values over a time range"""
        base_url, api_token, datasource_uid = await self._get_workspace_config(workspace_id)

        promql_query = self._build_promql_query(
            metric_name,
            service_name=service_name,
            labels=labels
        )

        start_time = self._format_time(time_range.start)
        end_time = self._format_time(time_range.end)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response_data = await self._query_grafana(
                client, base_url, api_token, datasource_uid,
                promql_query, start_time, end_time, time_range.step,
                workspace_id=workspace_id
            )

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
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get CPU usage metrics for a service"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        label_filter = self._build_label_filter(service_name=service_name)
        query = f"rate(process_cpu_seconds_total{label_filter}[5m]) * 100"

        # Call get_range_metrics with the constructed query
        return await self.get_range_metrics(query, time_range, workspace_id)

    async def get_memory_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get memory usage metrics for a service"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        label_filter = self._build_label_filter(service_name=service_name)
        query = f"process_resident_memory_bytes{label_filter} / 1024 / 1024"  # Convert to MB

        return await self.get_range_metrics(query, time_range, workspace_id)

    async def get_http_request_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get HTTP request rate metrics for a service"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        label_filter = self._build_label_filter(service_name=service_name)
        query = f"rate(http_requests_total{label_filter}[5m])"

        return await self.get_range_metrics(query, time_range, workspace_id)

    async def get_http_latency_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None,
        percentile: float = 0.95
    ) -> RangeMetricResponse:
        """Get HTTP request latency metrics for a service"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        label_filter = self._build_label_filter(service_name=service_name)
        query = f"histogram_quantile({percentile}, rate(http_request_duration_seconds_bucket{label_filter}[5m]))"

        return await self.get_range_metrics(query, time_range, workspace_id)

    async def get_error_rate_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get error rate metrics for a service"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        # Build label filter with service_name and status filter
        if service_name:
            # Combine status filter with service filter
            query = f'rate(http_requests_total{{status=~"5..",job="{service_name}"}}[5m])'
        else:
            # Status filter only
            query = 'rate(http_requests_total{status=~"5.."}[5m])'

        return await self.get_range_metrics(query, time_range, workspace_id)

    async def get_throughput_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get throughput metrics for a service"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        label_filter = self._build_label_filter(service_name=service_name)
        # Group by job to maintain consistency with service_name filtering
        if service_name:
            # If filtering by service, group by job
            query = f"sum(rate(http_requests_total{label_filter}[5m])) by (job)"
        else:
            # If no filter, group by job to show all services
            query = "sum(rate(http_requests_total[5m])) by (job)"

        return await self.get_range_metrics(query, time_range, workspace_id)

    async def get_availability_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get service availability metrics"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        label_filter = self._build_label_filter(service_name=service_name)
        query = f"up{label_filter}"

        return await self.get_range_metrics(query, time_range, workspace_id)

    async def get_all_metric_names(self, workspace_id: str, retry_on_auth_error: bool = True) -> List[str]:
        """Get list of all available metric names via Grafana datasource proxy"""
        base_url, api_token, datasource_uid = await self._get_workspace_config(workspace_id)
        # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
        url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/api/v1/label/__name__/values"

        headers = self._get_headers(api_token)
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                response_data = response.json()

                if response_data.get("status") == "success":
                    return response_data.get("data", [])
                else:
                    logger.error(f"Failed to get metric names: {response_data}")
                    return []
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error getting metric names: {e.response.status_code} - {e.response.text}")
                return []
            except Exception as e:
                logger.error(f"Error getting metric names: {e}")
                return []

    async def get_targets_status(self, workspace_id: str, retry_on_auth_error: bool = True) -> TargetsResponse:
        """Get monitoring targets status via Grafana datasource proxy"""
        base_url, api_token, datasource_uid = await self._get_workspace_config(workspace_id)
        # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
        url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/api/v1/targets"

        headers = self._get_headers(api_token)
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, headers=headers)
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
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error getting targets status: {e.response.status_code} - {e.response.text}")
                return TargetsResponse(status="error", data={})
            except Exception as e:
                logger.error(f"Error getting targets status: {e}")
                return TargetsResponse(status="error", data={})

    async def get_all_labels(self, workspace_id: str, retry_on_auth_error: bool = True) -> LabelResponse:
        """Get list of all available metric label keys via Grafana datasource proxy"""
        base_url, api_token, datasource_uid = await self._get_workspace_config(workspace_id)
        # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
        url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/api/v1/labels"

        headers = self._get_headers(api_token)
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                response_data = response.json()

                if response_data.get("status") == "success":
                    return LabelResponse(
                        status="success",
                        data=response_data.get("data", [])
                    )
                else:
                    logger.error(f"Failed to get labels: {response_data}")
                    return LabelResponse(status="error", data=[])

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error getting labels: {e.response.status_code} - {e.response.text}")
                return LabelResponse(status="error", data=[])
            except Exception as e:
                logger.error(f"Error getting labels: {e}")
                return LabelResponse(status="error", data=[])

    async def get_label_values(self, workspace_id: str, label_name: str, retry_on_auth_error: bool = True) -> LabelResponse:
        """Get all values for a specific label via Grafana datasource proxy"""
        base_url, api_token, datasource_uid = await self._get_workspace_config(workspace_id)
        # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
        url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/api/v1/label/{label_name}/values"

        headers = self._get_headers(api_token)
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                response_data = response.json()

                if response_data.get("status") == "success":
                    return LabelResponse(
                        status="success",
                        data=response_data.get("data", [])
                    )
                else:
                    logger.error(f"Failed to get label values: {response_data}")
                    return LabelResponse(status="error", data=[])

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error getting label values: {e.response.status_code} - {e.response.text}")
                return LabelResponse(status="error", data=[])
            except Exception as e:
                logger.error(f"Error getting label values: {e}")
                return LabelResponse(status="error", data=[])

    async def health_check(self, workspace_id: str) -> bool:
        """Check if Grafana datasource proxy is healthy"""
        try:
            base_url, api_token, datasource_uid = await self._get_workspace_config(workspace_id)
            # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
            url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/api/v1/query"
            headers = self._get_headers(api_token)
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url, params={"query": "up"}, headers=headers)
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Grafana health check failed: {e}")
            return False


# Global service instance
metrics_service = MetricsService()
