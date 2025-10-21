import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any
from app.services.sqs.client import sqs_client

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    def __init__(self, worker_name: str):
        """
        Initialize the worker with a name and a stopped task state.

        Parameters:
            worker_name (str): Identifier for the worker instance; used in logging and monitoring.

        Notes:
            Sets the worker to a non-running state and clears any existing worker task reference.
        """
        self.worker_name = worker_name
        self.running = False
        self.worker_task = None

    async def start(self):
        """
        Start the worker's background polling loop.

        If the worker is not already running, mark it as running and schedule the internal task that polls the queue and processes messages. If the worker is already running, no action is taken.
        """
        if self.running:
            logger.warning(f"Worker {self.worker_name} is already running")
            return

        self.running = True
        self.worker_task = asyncio.create_task(self._run_worker())
        logger.info(f"Worker {self.worker_name} started")

    async def stop(self):
        """
        Stop the worker loop and cancel its background task.

        Sets the running flag to False, cancels the internal worker task if present, awaits its completion, and suppresses asyncio.CancelledError. Logs when the worker has stopped.
        """
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
        """
        Continuously polls the configured SQS queue, dispatches each message to process_message, and acknowledges messages when processed or unparseable.

        This loop runs while the worker's running flag is true. For each received message it:
        - deletes the message and logs an error if the message body could not be parsed,
        - calls process_message with the parsed message body and deletes the message after successful processing,
        - logs exceptions raised during individual message processing without stopping the loop.

        The loop exits immediately on cancellation and, on any other unexpected error, logs the exception and pauses for 5 seconds before retrying.
        """
        while self.running:
            try:
                messages = await sqs_client.receive_messages(
                    max_messages=1, wait_time=20
                )

                for message in messages:
                    if not self.running:
                        break

                    try:
                        parsed_body = message.get("ParsedBody")
                        if parsed_body is None:
                            logger.error(
                                f"Skipping message with unparseable body: {message['Body']}"
                            )
                            await sqs_client.delete_message(message["ReceiptHandle"])
                            continue

                        await self.process_message(parsed_body)

                        await sqs_client.delete_message(message["ReceiptHandle"])
                        logger.debug(
                            f"Worker {self.worker_name} processed message successfully"
                        )

                    except Exception:
                        logger.exception(
                            f"Worker {self.worker_name} failed to process message"
                        )

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(f"Worker {self.worker_name} encountered error")
                await asyncio.sleep(5)

    @abstractmethod
    async def process_message(self, message_body: Dict[str, Any]):
        """
        Handle a single parsed SQS message.

        Parameters:
            message_body (Dict[str, Any]): The decoded/parsed body of an SQS message to be processed by the worker. Implementations should perform the message's required processing and side effects.
        """
        pass
