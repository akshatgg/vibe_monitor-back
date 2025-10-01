import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List
import grpc
from grpc import aio as aio_grpc
import time

from opentelemetry.proto.logs.v1 import logs_pb2
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2_grpc
from opentelemetry.proto.common.v1 import common_pb2

from app.core.config import settings
from app.services.clickhouse.models import LogEntry
from app.ingestion.batch_processor import batch_processor

logger = logging.getLogger(__name__)


class OTelLogCollectorService(logs_service_pb2_grpc.LogsServiceServicer):
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=10)

    async def Export(self, request, context):
        print("⚽ resource received")
        try:
            log_entries = []

            for resource_logs in request.resource_logs:
                resource_attrs = self._extract_attributes(
                    resource_logs.resource.attributes if resource_logs.resource else []
                )

                workspace_id = resource_attrs.get("workspace.id", "default")
                client_id = resource_attrs.get("client.id", "unknown")
                service_name = resource_attrs.get("service.name", "")
                service_version = resource_attrs.get("service.version", "")

                for scope_logs in resource_logs.scope_logs:
                    for log_record in scope_logs.log_records:
                        log_entry = await self._convert_otel_log_to_log_entry(
                            log_record,
                            workspace_id,
                            client_id,
                            service_name,
                            service_version,
                            resource_attrs,
                        )
                        log_entries.append(log_entry)

            for log_entry in log_entries:
                await batch_processor.add_log(log_entry)

            response = logs_service_pb2.ExportLogsServiceResponse()
            response.partial_success.rejected_log_records = 0
            response.partial_success.error_message = ""

            return response

        except Exception as e:
            logger.error(f"Error processing OTLP logs request: {e}")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

    async def _convert_otel_log_to_log_entry(
        self,
        log_record: logs_pb2.LogRecord,
        workspace_id: str,
        client_id: str,
        service_name: str,
        service_version: str,
        resource_attrs: Dict[str, str],
    ) -> LogEntry:
        timestamp_ms = log_record.time_unix_nano // 1_000_000

        if timestamp_ms == 0:
            timestamp_ms = int(time.time() * 1000)

        severity_text = self._get_severity_text(log_record.severity_number)

        body = ""
        if log_record.body.string_value:
            body = log_record.body.string_value
        elif log_record.body.bytes_value:
            body = log_record.body.bytes_value.decode("utf-8", errors="ignore")

        log_attributes = self._extract_attributes(log_record.attributes)

        endpoint = log_attributes.get("http.route", log_attributes.get("url.path", ""))

        trace_id = ""
        if log_record.trace_id:
            trace_id = log_record.trace_id.hex()

        span_id = ""
        if log_record.span_id:
            span_id = log_record.span_id.hex()

        return LogEntry(
            workspace_id=workspace_id,
            client_id=client_id,
            timestamp_ms=timestamp_ms,
            severity_text=severity_text,
            severity_number=log_record.severity_number,
            body=body,
            resource_attributes=resource_attrs,
            log_attributes=log_attributes,
            trace_id=trace_id,
            span_id=span_id,
            endpoint=endpoint,
            service_name=service_name,
            service_version=service_version,
        )

    def _extract_attributes(
        self, attributes: List[common_pb2.KeyValue]
    ) -> Dict[str, str]:
        attrs = {}
        for attr in attributes:
            key = attr.key
            value = ""

            if attr.value.string_value:
                value = attr.value.string_value
            elif attr.value.int_value:
                value = str(attr.value.int_value)
            elif attr.value.double_value:
                value = str(attr.value.double_value)
            elif attr.value.bool_value:
                value = str(attr.value.bool_value).lower()
            elif attr.value.bytes_value:
                value = attr.value.bytes_value.decode("utf-8", errors="ignore")

            attrs[key] = value

        return attrs

    def _get_severity_text(self, severity_number: int) -> str:
        severity_mapping = {
            1: "TRACE",
            2: "TRACE2",
            3: "TRACE3",
            4: "TRACE4",
            5: "DEBUG",
            6: "DEBUG2",
            7: "DEBUG3",
            8: "DEBUG4",
            9: "INFO",
            10: "INFO2",
            11: "INFO3",
            12: "INFO4",
            13: "WARN",
            14: "WARN2",
            15: "WARN3",
            16: "WARN4",
            17: "ERROR",
            18: "ERROR2",
            19: "ERROR3",
            20: "ERROR4",
            21: "FATAL",
            22: "FATAL2",
            23: "FATAL3",
            24: "FATAL4",
        }
        return severity_mapping.get(severity_number, "INFO")


class OTelCollectorServer:
    def __init__(self):
        self.server = None
        self.port = settings.OTEL_GRPC_PORT

    async def start(self):
        try:
            self.server = aio_grpc.server()

            logs_service_pb2_grpc.add_LogsServiceServicer_to_server(
                OTelLogCollectorService(), self.server
            )

            listen_addr = f"[::]:{self.port}"
            self.server.add_insecure_port(listen_addr)

            await self.server.start()
            logger.info(f"OpenTelemetry gRPC collector started on port {self.port}")

        except Exception as e:
            logger.error(f"Failed to start OpenTelemetry gRPC collector: {e}")
            raise

    async def stop(self):
        if self.server:
            await self.server.stop(grace=30)
            logger.info("OpenTelemetry gRPC collector stopped")

    async def wait_for_termination(self):
        if self.server:
            await self.server.wait_for_termination()


otel_collector_server = OTelCollectorServer()
