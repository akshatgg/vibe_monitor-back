"""
OpenTelemetry configuration for VM-API
Exports metrics and logs via OTLP to LGTM stack
"""

import logging
import socket
from typing import Optional

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global references for shutdown
_meter_provider: Optional[MeterProvider] = None
_logger_provider: Optional[LoggerProvider] = None
_tracer_provider: Optional[TracerProvider] = None


def get_resource_attributes() -> Resource:
    """
    Create OpenTelemetry Resource with service metadata

    Returns:
        Resource with service.name, service.version, service.instance.id,
        deployment.environment, and host.name attributes
    """
    hostname = settings.HOSTNAME or socket.gethostname()

    return Resource.create(
        {
            "service.name": "vm-api",
            "service.version": settings.VERSION,
            "service.instance.id": hostname,
            "deployment.environment": settings.ENVIRONMENT or "unknown",
            "host.name": hostname,
        }
    )


def setup_otel_metrics(endpoint: str) -> MeterProvider:
    """
    Configure OpenTelemetry metrics with OTLP exporter

    Args:
        endpoint: OTLP endpoint URL (e.g., "http://ec2-ip:4317")

    Returns:
        MeterProvider instance
    """
    global _meter_provider

    resource = get_resource_attributes()

    # Create OTLP metric exporter with gRPC protocol
    otlp_exporter = OTLPMetricExporter(
        endpoint=endpoint,
        insecure=True,  # Can add TLS later
    )

    # Create periodic exporting metric reader (exports every 15 seconds)
    metric_reader = PeriodicExportingMetricReader(
        exporter=otlp_exporter,
        export_interval_millis=15000,  # 15 seconds (matches old Prometheus interval)
    )

    # Create meter provider with resource and reader
    _meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )

    # Set as global meter provider
    metrics.set_meter_provider(_meter_provider)

    logger.info(f"OpenTelemetry metrics configured with OTLP endpoint: {endpoint}")

    return _meter_provider


def setup_otel_logs(endpoint: str) -> LoggingHandler:
    """
    Configure OpenTelemetry logs with OTLP exporter

    Args:
        endpoint: OTLP endpoint URL (e.g., "http://ec2-ip:4317")

    Returns:
        LoggingHandler that can be attached to loguru
    """
    global _logger_provider

    resource = get_resource_attributes()

    # Create OTLP log exporter with gRPC protocol
    otlp_exporter = OTLPLogExporter(
        endpoint=endpoint,
        insecure=True,  # Can add TLS later
    )

    # Create logger provider with batch processor
    _logger_provider = LoggerProvider(resource=resource)
    _logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_exporter))

    # Set as global logger provider
    set_logger_provider(_logger_provider)

    # Create logging handler that bridges standard logging to OpenTelemetry
    handler = LoggingHandler(
        level=logging.NOTSET,
        logger_provider=_logger_provider,
    )

    logger.info(f"OpenTelemetry logs configured with OTLP endpoint: {endpoint}")

    return handler


def setup_otel_traces(endpoint: str) -> TracerProvider:
    """
    Configure OpenTelemetry traces with OTLP exporter (optional for future use)

    Args:
        endpoint: OTLP endpoint URL (e.g., "http://ec2-ip:4317")

    Returns:
        TracerProvider instance
    """
    global _tracer_provider

    resource = get_resource_attributes()

    # Create OTLP span exporter with gRPC protocol
    otlp_exporter = OTLPSpanExporter(
        endpoint=endpoint,
        insecure=True,  # Can add TLS later
    )

    # Create tracer provider
    _tracer_provider = TracerProvider(resource=resource)
    _tracer_provider.add_span_processor(
        BatchLogRecordProcessor(otlp_exporter)  # type: ignore
    )

    # Set as global tracer provider
    trace.set_tracer_provider(_tracer_provider)

    logger.info(f"OpenTelemetry traces configured with OTLP endpoint: {endpoint}")

    return _tracer_provider


def shutdown_otel():
    """
    Gracefully shutdown OpenTelemetry providers to flush remaining telemetry

    Should be called during application shutdown to ensure all data is exported
    """
    global _meter_provider, _logger_provider, _tracer_provider

    try:
        if _meter_provider:
            _meter_provider.shutdown()
            logger.info("OpenTelemetry metrics provider shutdown complete")
    except Exception as e:
        logger.error(f"Error shutting down OpenTelemetry metrics provider: {e}")

    try:
        if _logger_provider:
            _logger_provider.shutdown()
            logger.info("OpenTelemetry logs provider shutdown complete")
    except Exception as e:
        logger.error(f"Error shutting down OpenTelemetry logs provider: {e}")

    try:
        if _tracer_provider:
            _tracer_provider.shutdown()
            logger.info("OpenTelemetry traces provider shutdown complete")
    except Exception as e:
        logger.error(f"Error shutting down OpenTelemetry traces provider: {e}")
