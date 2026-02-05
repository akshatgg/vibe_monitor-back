"""
DataCollectorService - Fetches logs, metrics, and errors from integrations.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.health_review_system.data_collector.schemas import (
    CollectedData,
    ErrorData,
    LogEntry,
    MetricsData,
)
from app.log.service import logs_service
from app.metrics.service import metrics_service
from app.models import Service
from app.services.rca.capabilities import (
    Capability,
    ExecutionContext,
    IntegrationCapabilityResolver,
)

logger = logging.getLogger(__name__)


class DataCollectorService:
    """
    Service for collecting observability data from integrations.

    Supports multiple integration types:
    - Grafana (Loki for logs, Prometheus for metrics)
    - Datadog (logs and metrics)
    - NewRelic (logs and metrics)
    - CloudWatch (AWS logs and metrics)

    Uses IntegrationCapabilityResolver to determine available integrations
    and collects data from all available sources.
    """

    MAX_LOG_SAMPLES = 1000
    DEFAULT_SERVICE_LABEL = "job"  # Default Loki label for service name

    def __init__(self, db: AsyncSession):
        self.db = db
        self.capability_resolver = IntegrationCapabilityResolver(only_healthy=True)

    async def collect(
        self,
        workspace_id: str,
        service: Service,
        week_start: datetime,
        week_end: datetime,
    ) -> CollectedData:
        """
        Collect observability data for a service.

        Args:
            workspace_id: Workspace ID
            service: Service model
            week_start: Start of review period
            week_end: End of review period

        Returns:
            CollectedData with logs, metrics, and errors

        Raises:
            RuntimeError: If no integrations available or data collection fails
        """
        # Resolve capabilities once (to avoid concurrent DB access)
        context = await self.capability_resolver.resolve(workspace_id, self.db)

        logger.debug(
            f"Resolved capabilities for workspace {workspace_id}: "
            f"{sorted(c.value for c in context.capabilities)} | "
            f"Integrations: {list(context.integrations.keys())}"
        )

        # Fetch logs and metrics sequentially (to avoid session concurrency issues)
        logs = await self._collect_logs(workspace_id, service, week_start, week_end, context)
        metrics = await self._collect_metrics(workspace_id, service, week_start, week_end, context)

        # Extract errors from collected logs (no separate API call needed)
        errors = self._aggregate_errors_from_logs(logs)

        return CollectedData(
            logs=logs[: self.MAX_LOG_SAMPLES],
            log_count=len(logs),
            metrics=metrics,
            metric_count=self._count_metrics(metrics),
            errors=errors,
        )

    async def _collect_logs(
        self,
        workspace_id: str,
        service: Service,
        week_start: datetime,
        week_end: datetime,
        context: ExecutionContext,
    ) -> List[LogEntry]:
        """
        Collect logs from available integrations.

        Tries integrations in priority order:
        1. Grafana (Loki)
        2. Datadog
        3. NewRelic
        4. CloudWatch
        """
        logger.info(f"Collecting logs for service {service.name}")

        logs: List[LogEntry] = []

        # Try Grafana/Loki first
        if context.has_capability(Capability.LOGS):
            try:
                grafana_logs = await self._collect_grafana_logs(
                    workspace_id, service.name, week_start, week_end
                )
                logs.extend(grafana_logs)
                logger.info(f"Collected {len(grafana_logs)} logs from Grafana/Loki")
            except Exception as e:
                logger.warning(f"Failed to collect Grafana logs: {e}")

        # Try Datadog
        if context.has_capability(Capability.DATADOG_LOGS) and len(logs) < self.MAX_LOG_SAMPLES:
            try:
                datadog_logs = await self._collect_datadog_logs(
                    workspace_id, service.name, week_start, week_end
                )
                logs.extend(datadog_logs)
                logger.info(f"Collected {len(datadog_logs)} logs from Datadog")
            except Exception as e:
                logger.warning(f"Failed to collect Datadog logs: {e}")

        # Try NewRelic
        if context.has_capability(Capability.NEWRELIC_LOGS) and len(logs) < self.MAX_LOG_SAMPLES:
            try:
                newrelic_logs = await self._collect_newrelic_logs(
                    workspace_id, service.name, week_start, week_end
                )
                logs.extend(newrelic_logs)
                logger.info(f"Collected {len(newrelic_logs)} logs from NewRelic")
            except Exception as e:
                logger.warning(f"Failed to collect NewRelic logs: {e}")

        # Try CloudWatch
        if context.has_capability(Capability.AWS_LOGS) and len(logs) < self.MAX_LOG_SAMPLES:
            try:
                cloudwatch_logs = await self._collect_cloudwatch_logs(
                    workspace_id, service.name, week_start, week_end
                )
                logs.extend(cloudwatch_logs)
                logger.info(f"Collected {len(cloudwatch_logs)} logs from CloudWatch")
            except Exception as e:
                logger.warning(f"Failed to collect CloudWatch logs: {e}")

        if not logs:
            logger.warning(f"No logs collected for service {service.name}")

        return logs

    async def _collect_grafana_logs(
        self,
        workspace_id: str,
        service_name: str,
        week_start: datetime,
        week_end: datetime,
    ) -> List[LogEntry]:
        """Collect logs from Grafana/Loki using internal service."""
        from app.log.models import TimeRange as LogTimeRange

        logs = []

        try:
            # TimeRange expects ISO format strings, not datetime objects
            time_range = LogTimeRange(
                start=week_start.isoformat(),
                end=week_end.isoformat(),
            )

            # Use the built-in get_logs_by_service method
            response = await logs_service.get_logs_by_service(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
                limit=self.MAX_LOG_SAMPLES,
            )

            if response and response.data and response.data.result:
                for stream in response.data.result:
                    stream_labels = stream.stream or {}
                    for timestamp_ns, message in stream.values or []:
                        # Convert nanosecond timestamp to datetime
                        ts_seconds = int(timestamp_ns) / 1_000_000_000
                        ts = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)

                        # Detect log level from message
                        level = self._detect_log_level(message)

                        logs.append(LogEntry(
                            timestamp=ts,
                            level=level,
                            message=message,
                            attributes=stream_labels,
                        ))

        except Exception as e:
            logger.exception(f"Error querying Grafana logs: {e}")

        return logs

    async def _collect_datadog_logs(
        self,
        workspace_id: str,
        service_name: str,
        week_start: datetime,
        week_end: datetime,
    ) -> List[LogEntry]:
        """Collect logs from Datadog."""
        from app.datadog.Logs.schemas import SearchLogsRequest
        from app.datadog.Logs.service import datadog_logs_service

        logs = []

        try:
            # Build query for the service
            request = SearchLogsRequest(
                query=f"service:{service_name}",
                from_time=int(week_start.timestamp() * 1000),
                to_time=int(week_end.timestamp() * 1000),
                sort="desc",
                limit=self.MAX_LOG_SAMPLES,
            )

            response = await datadog_logs_service.search_logs(
                db=self.db, workspace_id=workspace_id, request=request
            )

            if response and response.data:
                for log_data in response.data:
                    # Extract timestamp
                    timestamp = datetime.now(timezone.utc)
                    if log_data.attributes and log_data.attributes.timestamp:
                        try:
                            timestamp = datetime.fromisoformat(
                                log_data.attributes.timestamp.replace("Z", "+00:00")
                            )
                        except (ValueError, AttributeError):
                            pass

                    # Extract message
                    message = ""
                    if log_data.attributes and log_data.attributes.message:
                        message = log_data.attributes.message

                    # Extract level
                    level = "INFO"
                    if log_data.attributes and log_data.attributes.status:
                        level = log_data.attributes.status.upper()

                    # Build attributes
                    attributes = {}
                    if log_data.attributes:
                        if log_data.attributes.service:
                            attributes["service"] = log_data.attributes.service
                        if log_data.attributes.host:
                            attributes["host"] = log_data.attributes.host

                    logs.append(LogEntry(
                        timestamp=timestamp,
                        level=level,
                        message=message,
                        attributes=attributes,
                    ))

        except Exception as e:
            logger.exception(f"Error querying Datadog logs: {e}")

        return logs

    async def _collect_newrelic_logs(
        self,
        workspace_id: str,
        service_name: str,
        week_start: datetime,
        week_end: datetime,
    ) -> List[LogEntry]:
        """Collect logs from NewRelic."""
        from app.newrelic.Logs.schemas import FilterLogsRequest
        from app.newrelic.Logs.service import newrelic_logs_service

        logs = []

        try:
            # Build filter request
            request = FilterLogsRequest(
                query=service_name,
                startTime=int(week_start.timestamp() * 1000),
                endTime=int(week_end.timestamp() * 1000),
                limit=self.MAX_LOG_SAMPLES,
            )

            response = await newrelic_logs_service.filter_logs(
                db=self.db, workspace_id=workspace_id, request=request
            )

            if response and response.logs:
                for log_data in response.logs:
                    # Convert timestamp from milliseconds
                    timestamp = datetime.now(timezone.utc)
                    if log_data.timestamp:
                        timestamp = datetime.fromtimestamp(
                            log_data.timestamp / 1000, tz=timezone.utc
                        )

                    # Extract message and level
                    message = log_data.message or ""
                    level = self._detect_log_level(message)

                    logs.append(LogEntry(
                        timestamp=timestamp,
                        level=level,
                        message=message,
                        attributes={},
                    ))

        except Exception as e:
            logger.exception(f"Error querying NewRelic logs: {e}")

        return logs

    async def _collect_cloudwatch_logs(
        self,
        workspace_id: str,
        service_name: str,
        week_start: datetime,
        week_end: datetime,
    ) -> List[LogEntry]:
        """Collect logs from AWS CloudWatch."""
        from app.aws.cloudwatch.Logs.schemas import FilterLogEventsRequest
        from app.aws.cloudwatch.Logs.service import cloudwatch_logs_service

        logs = []

        try:
            # Common log group patterns for the service
            log_group_patterns = [
                f"/aws/lambda/{service_name}",
                f"/ecs/{service_name}",
                f"/aws/ecs/{service_name}",
                f"/{service_name}",
            ]

            for log_group_name in log_group_patterns:
                try:
                    request = FilterLogEventsRequest(
                        logGroupName=log_group_name,
                        filterPattern="ERROR",  # Focus on errors for health review
                        startTime=int(week_start.timestamp() * 1000),
                        endTime=int(week_end.timestamp() * 1000),
                        limit=min(self.MAX_LOG_SAMPLES - len(logs), 500),
                    )

                    response = await cloudwatch_logs_service.filter_log_events(
                        db=self.db, workspace_id=workspace_id, request=request
                    )

                    if response and response.events:
                        for event in response.events:
                            # Convert timestamp from milliseconds
                            timestamp = datetime.fromtimestamp(
                                event.timestamp / 1000, tz=timezone.utc
                            )

                            message = event.message.strip() if event.message else ""
                            level = self._detect_log_level(message)

                            logs.append(LogEntry(
                                timestamp=timestamp,
                                level=level,
                                message=message,
                                attributes={"logGroup": log_group_name},
                            ))

                        logger.info(f"Collected {len(response.events)} logs from {log_group_name}")

                        if len(logs) >= self.MAX_LOG_SAMPLES:
                            break

                except Exception as e:
                    # Log group might not exist, continue to next pattern
                    logger.debug(f"Could not fetch from {log_group_name}: {e}")
                    continue

        except Exception as e:
            logger.exception(f"Error querying CloudWatch logs: {e}")

        return logs

    def _detect_log_level(self, message: str) -> str:
        """Detect log level from message content."""
        message_upper = message.upper()
        if "ERROR" in message_upper or "EXCEPTION" in message_upper:
            return "ERROR"
        elif "WARN" in message_upper:
            return "WARN"
        elif "DEBUG" in message_upper:
            return "DEBUG"
        elif "TRACE" in message_upper:
            return "TRACE"
        return "INFO"

    async def _collect_metrics(
        self,
        workspace_id: str,
        service: Service,
        week_start: datetime,
        week_end: datetime,
        context: ExecutionContext,
    ) -> MetricsData:
        """
        Collect metrics from available integrations.

        Aggregates metrics from all available sources and returns
        the best available data for each metric type.
        """
        logger.info(f"Collecting metrics for service {service.name}")

        # Initialize metrics with None (will be filled from available sources)
        latency_p50: Optional[float] = None
        latency_p99: Optional[float] = None
        error_rate: Optional[float] = None
        availability: Optional[float] = None
        throughput: Optional[float] = None

        # Try Grafana/Prometheus first
        if context.has_capability(Capability.METRICS):
            try:
                grafana_metrics = await self._collect_grafana_metrics(
                    workspace_id, service.name, week_start, week_end
                )
                # Merge metrics (prefer first non-None value)
                latency_p50 = latency_p50 or grafana_metrics.get("latency_p50")
                latency_p99 = latency_p99 or grafana_metrics.get("latency_p99")
                error_rate = error_rate or grafana_metrics.get("error_rate")
                availability = availability or grafana_metrics.get("availability")
                throughput = throughput or grafana_metrics.get("throughput")
                logger.info("Collected metrics from Grafana/Prometheus")
            except Exception as e:
                logger.warning(f"Failed to collect Grafana metrics: {e}")

        # Try Datadog
        if context.has_capability(Capability.DATADOG_METRICS):
            try:
                datadog_metrics = await self._collect_datadog_metrics(
                    workspace_id, service.name, week_start, week_end
                )
                latency_p50 = latency_p50 or datadog_metrics.get("latency_p50")
                latency_p99 = latency_p99 or datadog_metrics.get("latency_p99")
                error_rate = error_rate or datadog_metrics.get("error_rate")
                availability = availability or datadog_metrics.get("availability")
                throughput = throughput or datadog_metrics.get("throughput")
                logger.info("Collected metrics from Datadog")
            except Exception as e:
                logger.warning(f"Failed to collect Datadog metrics: {e}")

        # Try NewRelic
        if context.has_capability(Capability.NEWRELIC_METRICS):
            try:
                newrelic_metrics = await self._collect_newrelic_metrics(
                    workspace_id, service.name, week_start, week_end
                )
                latency_p50 = latency_p50 or newrelic_metrics.get("latency_p50")
                latency_p99 = latency_p99 or newrelic_metrics.get("latency_p99")
                error_rate = error_rate or newrelic_metrics.get("error_rate")
                availability = availability or newrelic_metrics.get("availability")
                throughput = throughput or newrelic_metrics.get("throughput")
                logger.info("Collected metrics from NewRelic")
            except Exception as e:
                logger.warning(f"Failed to collect NewRelic metrics: {e}")

        # Try CloudWatch
        if context.has_capability(Capability.AWS_METRICS):
            try:
                cloudwatch_metrics = await self._collect_cloudwatch_metrics(
                    workspace_id, service.name, week_start, week_end
                )
                latency_p50 = latency_p50 or cloudwatch_metrics.get("latency_p50")
                latency_p99 = latency_p99 or cloudwatch_metrics.get("latency_p99")
                error_rate = error_rate or cloudwatch_metrics.get("error_rate")
                availability = availability or cloudwatch_metrics.get("availability")
                throughput = throughput or cloudwatch_metrics.get("throughput")
                logger.info("Collected metrics from CloudWatch")
            except Exception as e:
                logger.warning(f"Failed to collect CloudWatch metrics: {e}")

        return MetricsData(
            latency_p50=latency_p50,
            latency_p99=latency_p99,
            error_rate=error_rate,
            availability=availability,
            throughput_per_minute=throughput,
        )

    async def _collect_grafana_metrics(
        self,
        workspace_id: str,
        service_name: str,
        week_start: datetime,
        week_end: datetime,
    ) -> dict:
        """Collect metrics from Grafana/Prometheus using internal service."""
        from app.metrics.models import TimeRange as MetricTimeRange

        metrics = {}
        time_range = MetricTimeRange(start=week_start, end=week_end, step="1h")

        try:
            # Get latency p99 using built-in method
            latency_p99_response = await metrics_service.get_http_latency_metrics(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
                percentile=0.99,
            )
            if latency_p99_response and latency_p99_response.result:
                for series in latency_p99_response.result:
                    values = [v.value for v in series.values if v.value is not None]
                    if values:
                        # Convert to milliseconds
                        metrics["latency_p99"] = sum(values) / len(values) * 1000

            # Get latency p50 using built-in method
            latency_p50_response = await metrics_service.get_http_latency_metrics(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
                percentile=0.50,
            )
            if latency_p50_response and latency_p50_response.result:
                for series in latency_p50_response.result:
                    values = [v.value for v in series.values if v.value is not None]
                    if values:
                        metrics["latency_p50"] = sum(values) / len(values) * 1000

            # Get error rate using built-in method
            error_response = await metrics_service.get_error_rate_metrics(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
            )
            if error_response and error_response.result:
                for series in error_response.result:
                    values = [v.value for v in series.values if v.value is not None]
                    if values:
                        metrics["error_rate"] = sum(values) / len(values)

            # Get availability using built-in method
            availability_response = await metrics_service.get_availability_metrics(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
            )
            if availability_response and availability_response.result:
                for series in availability_response.result:
                    values = [v.value for v in series.values if v.value is not None]
                    if values:
                        # Availability is typically 0 or 1, convert to percentage
                        metrics["availability"] = sum(values) / len(values) * 100

            # Get throughput using built-in method
            throughput_response = await metrics_service.get_throughput_metrics(
                workspace_id=workspace_id,
                service_name=service_name,
                time_range=time_range,
            )
            if throughput_response and throughput_response.result:
                for series in throughput_response.result:
                    values = [v.value for v in series.values if v.value is not None]
                    if values:
                        # Convert to requests per minute
                        metrics["throughput"] = sum(values) / len(values) * 60

        except Exception as e:
            logger.exception(f"Error querying Grafana metrics: {e}")

        return metrics

    async def _collect_datadog_metrics(
        self,
        workspace_id: str,
        service_name: str,
        week_start: datetime,
        week_end: datetime,
    ) -> dict:
        """Collect metrics from Datadog."""
        from app.datadog.Metrics.schemas import SimpleQueryRequest
        from app.datadog.Metrics.service import datadog_metrics_service

        metrics = {}

        try:
            # Query latency p99
            latency_request = SimpleQueryRequest(
                query=f"avg:trace.http.request.duration.by.service.99p{{service:{service_name}}}",
                from_timestamp=int(week_start.timestamp() * 1000),
                to_timestamp=int(week_end.timestamp() * 1000),
            )

            latency_response = await datadog_metrics_service.query_simple(
                db=self.db, workspace_id=workspace_id, request=latency_request
            )

            if latency_response and latency_response.points:
                values = [dp.value for dp in latency_response.points if dp.value is not None]
                if values:
                    # Datadog returns in nanoseconds, convert to milliseconds
                    metrics["latency_p99"] = (sum(values) / len(values)) / 1_000_000

            # Query error rate
            error_request = SimpleQueryRequest(
                query=f"sum:trace.http.request.errors{{service:{service_name}}}.as_rate() / sum:trace.http.request.hits{{service:{service_name}}}.as_rate() * 100",
                from_timestamp=int(week_start.timestamp() * 1000),
                to_timestamp=int(week_end.timestamp() * 1000),
            )

            error_response = await datadog_metrics_service.query_simple(
                db=self.db, workspace_id=workspace_id, request=error_request
            )

            if error_response and error_response.points:
                values = [dp.value for dp in error_response.points if dp.value is not None]
                if values:
                    metrics["error_rate"] = sum(values) / len(values)
                    metrics["availability"] = 100.0 - metrics["error_rate"]

            # Query throughput
            throughput_request = SimpleQueryRequest(
                query=f"sum:trace.http.request.hits{{service:{service_name}}}.as_rate()",
                from_timestamp=int(week_start.timestamp() * 1000),
                to_timestamp=int(week_end.timestamp() * 1000),
            )

            throughput_response = await datadog_metrics_service.query_simple(
                db=self.db, workspace_id=workspace_id, request=throughput_request
            )

            if throughput_response and throughput_response.points:
                values = [dp.value for dp in throughput_response.points if dp.value is not None]
                if values:
                    # Convert to requests per minute
                    metrics["throughput"] = (sum(values) / len(values)) * 60

        except Exception as e:
            logger.exception(f"Error querying Datadog metrics: {e}")

        return metrics

    async def _collect_newrelic_metrics(
        self,
        workspace_id: str,
        service_name: str,
        week_start: datetime,
        week_end: datetime,
    ) -> dict:
        """Collect metrics from NewRelic."""
        from app.newrelic.Metrics.schemas import GetTimeSeriesRequest
        from app.newrelic.Metrics.service import newrelic_metrics_service

        metrics = {}

        try:
            # Query duration (latency)
            duration_request = GetTimeSeriesRequest(
                metric_name="duration",
                startTime=int(week_start.timestamp()),
                endTime=int(week_end.timestamp()),
                aggregation="percentile",
                timeseries=True,
                where_clause=f"appName = '{service_name}'",
            )

            duration_response = await newrelic_metrics_service.get_time_series(
                db=self.db, workspace_id=workspace_id, request=duration_request
            )

            if duration_response and duration_response.dataPoints:
                values = [dp.value for dp in duration_response.dataPoints if dp.value is not None]
                if values:
                    # NewRelic returns in seconds, convert to milliseconds
                    metrics["latency_p99"] = (sum(values) / len(values)) * 1000

            # Query error count and calculate rate
            # Using NRQL via query_metrics for error rate
            from app.newrelic.Metrics.schemas import QueryMetricsRequest

            error_request = QueryMetricsRequest(
                nrql_query=f"SELECT percentage(count(*), WHERE error IS true) as error_rate FROM Transaction WHERE appName = '{service_name}' SINCE {int((datetime.now(timezone.utc) - week_start).total_seconds() / 3600)} hours ago"
            )

            error_response = await newrelic_metrics_service.query_metrics(
                db=self.db, workspace_id=workspace_id, request=error_request
            )

            if error_response and error_response.results:
                for result in error_response.results:
                    if result.get("error_rate") is not None:
                        metrics["error_rate"] = float(result["error_rate"])
                        metrics["availability"] = 100.0 - metrics["error_rate"]
                        break

            # Query throughput
            throughput_request = QueryMetricsRequest(
                nrql_query=f"SELECT rate(count(*), 1 minute) as throughput FROM Transaction WHERE appName = '{service_name}' SINCE {int((datetime.now(timezone.utc) - week_start).total_seconds() / 3600)} hours ago"
            )

            throughput_response = await newrelic_metrics_service.query_metrics(
                db=self.db, workspace_id=workspace_id, request=throughput_request
            )

            if throughput_response and throughput_response.results:
                for result in throughput_response.results:
                    if "throughput" in result:
                        metrics["throughput"] = float(result["throughput"])
                        break

        except Exception as e:
            logger.exception(f"Error querying NewRelic metrics: {e}")

        return metrics

    async def _collect_cloudwatch_metrics(
        self,
        workspace_id: str,
        service_name: str,
        week_start: datetime,
        week_end: datetime,
    ) -> dict:
        """Collect metrics from AWS CloudWatch."""
        from app.aws.cloudwatch.Metrics.schemas import Dimension, GetMetricStatisticsRequest
        from app.aws.cloudwatch.Metrics.service import cloudwatch_metrics_service

        metrics = {}

        try:
            # Common metric configurations for Lambda functions
            dimension = Dimension(Name="FunctionName", Value=service_name)

            # Query Duration (latency) - Lambda
            duration_request = GetMetricStatisticsRequest(
                Namespace="AWS/Lambda",
                MetricName="Duration",
                Dimensions=[dimension],
                StartTime=int(week_start.timestamp()),
                EndTime=int(week_end.timestamp()),
                Period=3600,  # 1 hour
                Statistics=["p99"],
                MaxDatapoints=168,  # 7 days * 24 hours
            )

            duration_response = await cloudwatch_metrics_service.get_metric_statistics(
                db=self.db, workspace_id=workspace_id, request=duration_request
            )

            if duration_response and duration_response.Datapoints:
                values = []
                for dp in duration_response.Datapoints:
                    if hasattr(dp, "ExtendedStatistics") and dp.ExtendedStatistics:
                        if "p99" in dp.ExtendedStatistics:
                            values.append(dp.ExtendedStatistics["p99"])
                    elif dp.Average is not None:
                        values.append(dp.Average)

                if values:
                    metrics["latency_p99"] = sum(values) / len(values)

            # Query Errors
            errors_request = GetMetricStatisticsRequest(
                Namespace="AWS/Lambda",
                MetricName="Errors",
                Dimensions=[dimension],
                StartTime=int(week_start.timestamp()),
                EndTime=int(week_end.timestamp()),
                Period=3600,
                Statistics=["Sum"],
                MaxDatapoints=168,
            )

            errors_response = await cloudwatch_metrics_service.get_metric_statistics(
                db=self.db, workspace_id=workspace_id, request=errors_request
            )

            # Query Invocations for error rate calculation
            invocations_request = GetMetricStatisticsRequest(
                Namespace="AWS/Lambda",
                MetricName="Invocations",
                Dimensions=[dimension],
                StartTime=int(week_start.timestamp()),
                EndTime=int(week_end.timestamp()),
                Period=3600,
                Statistics=["Sum"],
                MaxDatapoints=168,
            )

            invocations_response = await cloudwatch_metrics_service.get_metric_statistics(
                db=self.db, workspace_id=workspace_id, request=invocations_request
            )

            if errors_response and invocations_response:
                error_sum = sum(
                    dp.Sum for dp in (errors_response.Datapoints or [])
                    if dp.Sum is not None
                )
                invocation_sum = sum(
                    dp.Sum for dp in (invocations_response.Datapoints or [])
                    if dp.Sum is not None
                )

                if invocation_sum > 0:
                    metrics["error_rate"] = (error_sum / invocation_sum) * 100
                    metrics["availability"] = 100.0 - metrics["error_rate"]
                    # Calculate throughput (per minute)
                    total_hours = (week_end - week_start).total_seconds() / 3600
                    if total_hours > 0:
                        metrics["throughput"] = invocation_sum / (total_hours * 60)

        except Exception as e:
            logger.exception(f"Error querying CloudWatch metrics: {e}")

        return metrics

    def _aggregate_errors_from_logs(self, logs: List[LogEntry]) -> List[ErrorData]:
        """
        Aggregate and fingerprint errors from collected logs.

        Groups errors by fingerprint (hash of error type + message pattern)
        to identify unique error types and their frequency.

        Args:
            logs: List of collected log entries

        Returns:
            List of aggregated ErrorData objects
        """
        # Filter to only ERROR level logs
        error_logs = [log for log in logs if log.level == "ERROR"]

        if not error_logs:
            logger.info("No error logs found")
            return []

        # Aggregate errors by fingerprint
        error_map: dict = {}

        for log in error_logs:
            # Generate fingerprint from error message
            error_type, fingerprint = self._fingerprint_error(log.message)

            if fingerprint in error_map:
                error_map[fingerprint]["count"] += 1
                error_map[fingerprint]["last_seen"] = max(
                    error_map[fingerprint]["last_seen"], log.timestamp
                )
                # Extract endpoint from log attributes if available
                endpoint = log.attributes.get("endpoint") or log.attributes.get("path")
                if endpoint and endpoint not in error_map[fingerprint]["endpoints"]:
                    error_map[fingerprint]["endpoints"].append(endpoint)
            else:
                endpoint = log.attributes.get("endpoint") or log.attributes.get("path")
                error_map[fingerprint] = {
                    "fingerprint": fingerprint,
                    "error_type": error_type,
                    "message_sample": log.message[:500],  # Truncate long messages
                    "count": 1,
                    "first_seen": log.timestamp,
                    "last_seen": log.timestamp,
                    "endpoints": [endpoint] if endpoint else [],
                    "stack_trace": self._extract_stack_trace(log.message),
                }

        # Convert to ErrorData objects, sorted by count descending
        errors = [
            ErrorData(
                fingerprint=data["fingerprint"],
                error_type=data["error_type"],
                message_sample=data["message_sample"],
                count=data["count"],
                first_seen=data["first_seen"],
                last_seen=data["last_seen"],
                endpoints=data["endpoints"][:10],  # Limit to 10 endpoints
                stack_trace=data["stack_trace"],
            )
            for data in sorted(
                error_map.values(), key=lambda x: x["count"], reverse=True
            )
        ]

        logger.info(f"Found {len(errors)} unique error types from {len(error_logs)} error logs")
        return errors

    def _fingerprint_error(self, message: str) -> tuple[str, str]:
        """
        Generate a fingerprint for an error message.

        Returns:
            Tuple of (error_type, fingerprint_hash)
        """
        # Extract error type (e.g., "ValueError", "ConnectionError", etc.)
        error_type = "UnknownError"

        # Common error type patterns
        patterns = [
            r"(\w+Error):",
            r"(\w+Exception):",
            r"Error:\s*(\w+)",
            r"Exception:\s*(\w+)",
            r"^\[?(\w+Error)\]?",
            r"^\[?(\w+Exception)\]?",
        ]

        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                error_type = match.group(1)
                break

        # Normalize message for fingerprinting:
        # - Remove timestamps
        # - Remove UUIDs
        # - Remove numbers (IDs, line numbers, etc.)
        # - Remove specific values
        normalized = message

        # Remove common variable patterns
        normalized = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<UUID>", normalized)
        normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", "<TIMESTAMP>", normalized)
        normalized = re.sub(r"\b\d+\b", "<NUM>", normalized)
        normalized = re.sub(r'"[^"]*"', '"<STR>"', normalized)
        normalized = re.sub(r"'[^']*'", "'<STR>'", normalized)

        # Generate fingerprint hash
        fingerprint = hashlib.md5(f"{error_type}:{normalized}".encode()).hexdigest()[:16]

        return error_type, fingerprint

    def _extract_stack_trace(self, message: str) -> Optional[str]:
        """Extract stack trace from error message if present."""
        # Look for common stack trace patterns
        patterns = [
            r"(Traceback \(most recent call last\):.*?)(?=\n\n|\Z)",
            r"(at [\w\.$]+\([\w\.]+:\d+\).*?)(?=\n\n|\Z)",
            r"(File \"[^\"]+\", line \d+.*?)(?=\n\n|\Z)",
        ]

        for pattern in patterns:
            match = re.search(pattern, message, re.DOTALL)
            if match:
                return match.group(1)[:2000]  # Truncate long stack traces

        return None

    def _count_metrics(self, metrics: MetricsData) -> int:
        """Count non-null metrics."""
        count = 0
        if metrics.latency_p50 is not None:
            count += 1
        if metrics.latency_p99 is not None:
            count += 1
        if metrics.error_rate is not None:
            count += 1
        if metrics.availability is not None:
            count += 1
        if metrics.throughput_per_minute is not None:
            count += 1
        return count
