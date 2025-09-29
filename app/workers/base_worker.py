import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any
from app.services.sqs.client import sqs_client

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    def __init__(self, worker_name: str):
        self.worker_name = worker_name
        self.running = False
        self.worker_task = None

    async def start(self):
        if self.running:
            logger.warning(f"Worker {self.worker_name} is already running")
            return

        self.running = True
        self.worker_task = asyncio.create_task(self._run_worker())
        logger.info(f"Worker {self.worker_name} started")

    async def stop(self):
        if not self.running:
            return

        self.running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

        logger.info(f"Worker {self.worker_name} stopped")

    async def _run_worker(self):
        while self.running:
            try:
                messages = await sqs_client.receive_messages(max_messages=1, wait_time=20)

                for message in messages:
                    if not self.running:
                        break

                    try:
                        parsed_body = message.get('ParsedBody')
                        if parsed_body is None:
                            logger.error(f"Skipping message with unparseable body: {message['Body']}")
                            await sqs_client.delete_message(message['ReceiptHandle'])
                            continue

                        await self.process_message(parsed_body)

                        await sqs_client.delete_message(message['ReceiptHandle'])
                        logger.debug(f"Worker {self.worker_name} processed message successfully")

                    except Exception as e:
                        logger.error(f"Worker {self.worker_name} failed to process message: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {self.worker_name} encountered error: {e}")
                await asyncio.sleep(5)

    @abstractmethod
    async def process_message(self, message_body: Dict[str, Any]):
        pass