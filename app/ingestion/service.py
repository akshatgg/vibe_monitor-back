import time
import uuid
from app.ingestion.schemas import LogQueryRequest, LogQueryResponse, IngestionStatsResponse
from app.services.clickhouse.service import clickhouse_service
from app.services.clickhouse.models import LogQueryFilters
from app.ingestion.batch_processor import batch_processor


class IngestionService:
    async def query_logs(self, request: LogQueryRequest) -> LogQueryResponse:
        start_time = time.time()
        request_id = str(uuid.uuid4())

        filters = LogQueryFilters(
            workspace_id=request.workspace_id,
            start_time_ms=request.start_time_ms,
            end_time_ms=request.end_time_ms,
            severity_filter=request.severity_filter,
            search_query=request.search_query,
            client_id=request.client_id,
            endpoint=request.endpoint,
            limit=request.limit,
            offset=request.offset,
            sort_order=request.sort_order,
        )

        result = await clickhouse_service.query_logs(filters)

        execution_time_ms = (time.time() - start_time) * 1000

        return LogQueryResponse(
            logs=result.logs,
            total_count=result.total_count,
            has_more=result.has_more,
            request_id=request_id,
            execution_time_ms=execution_time_ms,
        )

    async def get_ingestion_stats(self) -> IngestionStatsResponse:
        batch_stats = await batch_processor.get_stats()
        clickhouse_health = await clickhouse_service.health_check()

        otel_status = "running" if batch_processor.running else "stopped"

        return IngestionStatsResponse(
            batch_processor_stats=batch_stats,
            clickhouse_health=clickhouse_health,
            otel_collector_status=otel_status,
        )


ingestion_service = IngestionService()