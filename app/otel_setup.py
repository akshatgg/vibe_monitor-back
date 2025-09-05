import logging
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FASTAPI_INSTRUMENTATION_AVAILABLE = True
except ImportError:
    FASTAPI_INSTRUMENTATION_AVAILABLE = False

def setup_otel(app, service_name="vm-api"):
    resource = Resource.create({"service.name": service_name})
    
    trace_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(trace_provider)
    
    metrics_provider = MeterProvider(resource=resource)
    metrics.set_meter_provider(metrics_provider)
    
    logger_provider = LoggerProvider(resource=resource)
    set_logger_provider(logger_provider)
    
    from app.otel_processor import SlackErrorLogProcessor
    slack_processor = SlackErrorLogProcessor()
    logger_provider.add_log_record_processor(slack_processor)
    
    handler = LoggingHandler(level=logging.ERROR, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    
    if FASTAPI_INSTRUMENTATION_AVAILABLE:
        FastAPIInstrumentor.instrument_app(app)
    
    return logger_provider