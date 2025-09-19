import asyncio
import logging
from typing import List, Dict, Any
import time
from collections import defaultdict
from app.core.config import settings
from app.services.clickhouse.models import LogEntry
from app.services.clickhouse.service import clickhouse_service
from datetime import datetime

logger = logging.getLogger(__name__)


class LogBatchProcessor:
    def __init__(self):
        self.batch_size = settings.LOG_BATCH_SIZE
        self.batch_timeout = settings.LOG_BATCH_TIMEOUT
        self.batches: Dict[str, List[LogEntry]] = defaultdict(list)
        self.batch_timestamps: Dict[str, float] = {}
        self.processing_lock = asyncio.Lock()
        self.background_task: asyncio.Task = None
        self.running = False

    async def start(self):
        if self.running:
            return

        self.running = True
        self.background_task = asyncio.create_task(self._background_processor())
        logger.info("LogBatchProcessor started")

    async def stop(self):
        self.running = False
        if self.background_task:
            self.background_task.cancel()
            try:
                await self.background_task
            except asyncio.CancelledError:
                pass

        await self._flush_all_batches()
        logger.info("LogBatchProcessor stopped")

    async def add_log(self, log_entry: LogEntry):
        async with self.processing_lock:
            batch_key = f"{log_entry.workspace_id}:{log_entry.client_id}"

            if batch_key not in self.batch_timestamps:
                self.batch_timestamps[batch_key] = time.time()

            self.batches[batch_key].append(log_entry)

            if len(self.batches[batch_key]) >= self.batch_size:
                await self._flush_batch(batch_key)

    async def _background_processor(self):
        while self.running:
            try:
                await asyncio.sleep(5)
                current_time = time.time()

                async with self.processing_lock:
                    batches_to_flush = []

                    for batch_key, timestamp in self.batch_timestamps.items():
                        if (current_time - timestamp) >= self.batch_timeout:
                            if self.batches[batch_key]:
                                batches_to_flush.append(batch_key)

                    for batch_key in batches_to_flush:
                        await self._flush_batch(batch_key)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background batch processor: {e}")

    async def _flush_batch(self, batch_key: str):
        if not self.batches[batch_key]:
            return

        logs_to_process = self.batches[batch_key].copy()
        self.batches[batch_key].clear()
        del self.batch_timestamps[batch_key]

        try:
            success = await clickhouse_service.store_logs_batch(logs_to_process)
            if success:
                india_time = datetime.now().astimezone().strftime("%H:%M:%S")
                logger.info(f"Successfully flushed batch {batch_key} with {len(logs_to_process)} logs at {india_time} (IST)")
            else:
                logger.error(f"Failed to flush batch {batch_key}, re-queuing logs")
                self.batches[batch_key].extend(logs_to_process)
                self.batch_timestamps[batch_key] = time.time()
        except Exception as e:
            logger.error(f"Error flushing batch {batch_key}: {e}")
            self.batches[batch_key].extend(logs_to_process)
            self.batch_timestamps[batch_key] = time.time()

    async def _flush_all_batches(self):
        async with self.processing_lock:
            batch_keys = list(self.batches.keys())
            for batch_key in batch_keys:
                if self.batches[batch_key]:
                    await self._flush_batch(batch_key)

    async def get_stats(self) -> Dict[str, Any]:
        async with self.processing_lock:
            stats = {
                "total_batches": len(self.batches),
                "total_pending_logs": sum(len(batch) for batch in self.batches.values()),
                "batch_details": {},
                "running": self.running,
            }

            for batch_key, logs in self.batches.items():
                if logs:
                    stats["batch_details"][batch_key] = {
                        "pending_logs": len(logs),
                        "batch_age_seconds": time.time() - self.batch_timestamps.get(batch_key, 0),
                    }

            return stats


batch_processor = LogBatchProcessor()