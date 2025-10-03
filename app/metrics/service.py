"""
Metrics service layer for business logic
"""
import logging
from typing import List
from sqlalchemy import select

from ..core.database import AsyncSessionLocal
from ..models import GrafanaIntegration
from .models import (
    InstantMetricResponse,
    RangeMetricResponse,
    TargetsResponse,
    MetricQueryParams,
    TimeRange
)
from .providers.grafana import GrafanaProvider
from .utils import get_prometheus_uid_cached

logger = logging.getLogger(__name__)


class MetricsService:
    """Service layer for metrics operations - DB-only, no fallback"""

    def __init__(self):
        self._provider_cache: dict[str, GrafanaProvider] = {}

    async def _get_provider_for_workspace(self, workspace_id: str) -> GrafanaProvider:
        """Get Grafana provider for a specific workspace from database"""
        # Check cache first
        if workspace_id in self._provider_cache:
            return self._provider_cache[workspace_id]

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

            # Create provider from database config
            provider = GrafanaProvider(
                base_url=integration.grafana_url,
                api_key=integration.api_token,
                datasource_uid=datasource_uid
            )

            # Cache the provider
            self._provider_cache[workspace_id] = provider

            return provider

    async def get_instant_metrics(
        self,
        metric_name: str,
        workspace_id: str,
        service_name: str = None,
        labels: dict = None,
        timeout: str = None
    ) -> InstantMetricResponse:
        """Get instant metric values"""
        provider = await self._get_provider_for_workspace(workspace_id)

        params = MetricQueryParams(
            service_name=service_name,
            labels=labels,
            timeout=timeout
        )

        return await provider.get_instant_metrics(metric_name, params)

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
        provider = await self._get_provider_for_workspace(workspace_id)

        params = MetricQueryParams(
            service_name=service_name,
            labels=labels,
            timeout=timeout
        )

        return await provider.get_range_metrics(metric_name, time_range, params)

    async def get_cpu_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get CPU usage metrics for a service"""
        provider = await self._get_provider_for_workspace(workspace_id)
        return await provider.get_cpu_metrics(service_name, time_range)

    async def get_memory_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get memory usage metrics for a service"""
        provider = await self._get_provider_for_workspace(workspace_id)
        return await provider.get_memory_metrics(service_name, time_range)

    async def get_http_request_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get HTTP request rate metrics for a service"""
        provider = await self._get_provider_for_workspace(workspace_id)
        return await provider.get_http_request_metrics(service_name, time_range)

    async def get_http_latency_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None,
        percentile: float = 0.95
    ) -> RangeMetricResponse:
        """Get HTTP request latency metrics for a service"""
        provider = await self._get_provider_for_workspace(workspace_id)
        return await provider.get_http_latency_metrics(service_name, time_range, percentile)

    async def get_error_rate_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get error rate metrics for a service"""
        provider = await self._get_provider_for_workspace(workspace_id)
        return await provider.get_error_rate_metrics(service_name, time_range)

    async def get_throughput_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get throughput metrics for a service"""
        provider = await self._get_provider_for_workspace(workspace_id)
        return await provider.get_throughput_metrics(service_name, time_range)

    async def get_availability_metrics(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None
    ) -> RangeMetricResponse:
        """Get service availability metrics"""
        provider = await self._get_provider_for_workspace(workspace_id)
        return await provider.get_availability_metrics(service_name, time_range)

    async def get_all_metric_names(self, workspace_id: str) -> List[str]:
        """Get list of all available metric names"""
        provider = await self._get_provider_for_workspace(workspace_id)
        return await provider.get_all_metric_names()

    async def get_targets_status(self, workspace_id: str) -> TargetsResponse:
        """Get monitoring targets status"""
        provider = await self._get_provider_for_workspace(workspace_id)
        return await provider.get_targets_status()

    async def health_check(self, workspace_id: str) -> bool:
        """Check if the metrics provider is healthy"""
        provider = await self._get_provider_for_workspace(workspace_id)
        return await provider.health_check()


# Global service instance
metrics_service = MetricsService()
