import asyncio
import logging
from typing import List
from .client import ClickHouseClient
from .models import LogEntry, LogQueryFilters, LogQueryResponse

logger = logging.getLogger(__name__)


class ClickHouseService:
    def __init__(self):
        self.client = ClickHouseClient()
        self.schema_initialized = False

    def _ensure_schema(self):
        if self.schema_initialized:
            return
        try:
            self.client.create_logs_table()
            self.schema_initialized = True
            logger.info("ClickHouse schema initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize ClickHouse schema: {e}")
            raise

    async def store_logs_batch(self, logs: List[LogEntry]) -> bool:
        if not logs:
            return True

        self._ensure_schema()
        log_dicts = []
        for log in logs:
            log_dict = {
                "id": log.id,
                "workspace_id": log.workspace_id,
                "client_id": log.client_id,
                "timestamp_ms": log.timestamp_ms,
                "severity_text": log.severity_text,
                "severity_number": log.severity_number,
                "body": log.body,
                "resource_attributes": log.resource_attributes,
                "log_attributes": log.log_attributes,
                "trace_id": log.trace_id,
                "span_id": log.span_id,
                "endpoint": log.endpoint,
                "service_name": log.service_name,
                "service_version": log.service_version,
            }
            log_dicts.append(log_dict)

        return await asyncio.get_event_loop().run_in_executor(
            None, self.client.insert_logs_batch, log_dicts
        )

    async def query_logs(self, filters: LogQueryFilters) -> LogQueryResponse:
        self._ensure_schema()
        loop = asyncio.get_event_loop()

        logs_task = loop.run_in_executor(
            None,
            self.client.query_logs,
            filters.workspace_id,
            filters.start_time_ms,
            filters.end_time_ms,
            filters.severity_filter,
            filters.search_query,
            filters.client_id,
            filters.endpoint,
            filters.limit,
            filters.offset,
            filters.sort_order,
        )

        count_task = loop.run_in_executor(
            None,
            self.client.count_logs,
            filters.workspace_id,
            filters.start_time_ms,
            filters.end_time_ms,
            filters.severity_filter,
            filters.search_query,
            filters.client_id,
            filters.endpoint,
        )

        logs, total_count = await asyncio.gather(logs_task, count_task)

        has_more = (filters.offset + len(logs)) < total_count

        return LogQueryResponse(
            logs=logs,
            total_count=total_count,
            has_more=has_more,
            filters_applied=filters,
        )

    async def health_check(self) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.client.health_check)


clickhouse_service = ClickHouseService()