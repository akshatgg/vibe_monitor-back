"""
HealthReviewWorker - Processes health review generation jobs from SQS.
"""

import asyncio
import json
import logging
import signal
from datetime import datetime, timezone
from typing import Any, Dict

import aioboto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)

from dotenv import load_dotenv

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging_config import clear_job_id, set_job_id
from app.core.sentry import clear_sentry_context, set_sentry_context
from app.health_review_system.orchestrator import ReviewOrchestrator
from app.health_review_system.orchestrator.schemas import ReviewGenerationRequest
from app.models import ReviewStatus, ServiceReview

logger = logging.getLogger(__name__)


class HealthReviewSQSClient:
    """SQS client for health review queue."""

    def __init__(self):
        self.queue_url = settings.HEALTH_REVIEW_QUEUE_URL
        self.region = settings.AWS_REGION
        self._session = None
        self._sqs = None

    async def _get_sqs_client(self):
        """Initialize and return the SQS client."""
        if self._sqs is None:
            self._session = aioboto3.Session()
            if not self.region:
                logger.error("AWS_REGION not configured")
                raise ValueError("AWS_REGION not configured")
            client_kwargs = {"region_name": self.region}

            if settings.AWS_ENDPOINT_URL and settings.is_local:
                client_kwargs["endpoint_url"] = settings.AWS_ENDPOINT_URL
                logger.info(
                    f"Health review SQS client using LocalStack endpoint: {settings.AWS_ENDPOINT_URL}"
                )

            self._sqs = await self._session.client("sqs", **client_kwargs).__aenter__()
        return self._sqs

    async def send_message(
        self, message_body: Dict[str, Any], delay_seconds: int = 0
    ) -> bool:
        """Send a message to the health review queue."""
        try:
            if not self.queue_url:
                logger.error("HEALTH_REVIEW_QUEUE_URL not configured")
                return False

            sqs = await self._get_sqs_client()

            response = await sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(message_body),
                DelaySeconds=delay_seconds,
            )

            logger.debug(
                f"Health review message sent to SQS: {response.get('MessageId')}"
            )
            return True

        except (
            ClientError,
            EndpointConnectionError,
            NoCredentialsError,
            BotoCoreError,
        ):
            logger.exception("Failed to send message to health review SQS")
            return False
        except Exception:
            logger.exception(
                "Unexpected error while sending message to health review SQS"
            )
            return False

    async def receive_messages(
        self, max_messages: int = 1, wait_time: int = 20
    ) -> list:
        """Receive messages from the health review queue."""
        try:
            if not self.queue_url:
                logger.error("HEALTH_REVIEW_QUEUE_URL not configured")
                return []

            sqs = await self._get_sqs_client()

            response = await sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time,
                MessageAttributeNames=["All"],
            )

            messages = response.get("Messages", [])

            for message in messages:
                try:
                    message["ParsedBody"] = json.loads(message["Body"])
                except json.JSONDecodeError:
                    logger.exception(f"Failed to parse message body: {message['Body']}")
                    message["ParsedBody"] = None

            return messages

        except (
            ClientError,
            EndpointConnectionError,
            NoCredentialsError,
            BotoCoreError,
        ):
            logger.exception("Failed to receive messages from health review SQS")
            return []
        except Exception:
            logger.exception(
                "Unexpected error while receiving messages from health review SQS"
            )
            return []

    async def delete_message(self, receipt_handle: str) -> bool:
        """Delete a message from the health review queue."""
        try:
            if not self.queue_url:
                logger.error("HEALTH_REVIEW_QUEUE_URL not configured")
                return False

            sqs = await self._get_sqs_client()

            await sqs.delete_message(
                QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
            )

            logger.debug("Health review message deleted from SQS")
            return True

        except (
            ClientError,
            EndpointConnectionError,
            NoCredentialsError,
            BotoCoreError,
        ):
            logger.exception("Failed to delete message from health review SQS")
            return False
        except Exception:
            logger.exception(
                "Unexpected error while deleting message from health review SQS"
            )
            return False

    async def close(self):
        """Close the SQS client."""
        if self._sqs:
            await self._sqs.__aexit__(None, None, None)
            self._sqs = None
        self._session = None


# Singleton instance
health_review_sqs_client = HealthReviewSQSClient()


class HealthReviewWorker:
    """
    Worker that processes health review generation jobs from SQS.

    Message format:
    {
        "review_id": "uuid",
        "workspace_id": "uuid",
        "service_id": "uuid"
    }
    """

    def __init__(self):
        self.worker_name = "health-review-worker"
        self.running = False
        self.worker_task = None
        self.sqs_client = health_review_sqs_client

    async def start(self):
        """Start the worker's background polling loop."""
        if self.running:
            logger.warning(f"Worker {self.worker_name} is already running")
            return

        self.running = True
        self.worker_task = asyncio.create_task(self._run_worker())
        logger.info(f"Worker {self.worker_name} started")

    async def stop(self):
        """Stop the worker loop and cancel its background task."""
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
        """Main worker loop that polls SQS and processes messages."""
        while self.running:
            try:
                messages = await self.sqs_client.receive_messages(
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
                            await self.sqs_client.delete_message(
                                message["ReceiptHandle"]
                            )
                            continue

                        await self.process_message(parsed_body)

                        await self.sqs_client.delete_message(message["ReceiptHandle"])
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

    async def process_message(self, message_body: Dict[str, Any]):
        """
        Process a health review generation job.

        Args:
            message_body: Dict containing review_id, workspace_id, service_id
        """
        review_id = message_body.get("review_id")
        workspace_id = message_body.get("workspace_id")
        service_id = message_body.get("service_id")

        if not all([review_id, workspace_id, service_id]):
            logger.error(
                f"Invalid message body, missing required fields: {message_body}"
            )
            return

        set_sentry_context(
            job_id=review_id,
            workspace_id=workspace_id,
            service_id=service_id,
        )
        # Propagate review_id into the logging context so all logs emitted
        # during this review job automatically include the review_id field,
        # enabling full log tracing by review_id.
        set_job_id(review_id)

        logger.info(
            f"Processing health review job: review_id={review_id}, "
            f"service_id={service_id}, workspace_id={workspace_id}"
        )

        async with AsyncSessionLocal() as db:
            try:
                # Fetch the review
                review = await db.get(ServiceReview, review_id)
                if not review:
                    logger.error(f"Review {review_id} not found")
                    return

                # Validate status - only process QUEUED reviews
                if review.status != ReviewStatus.QUEUED:
                    logger.warning(
                        f"Review {review_id} is not in QUEUED status "
                        f"(current: {review.status.value}), skipping"
                    )
                    return

                # Run the orchestrator
                orchestrator = ReviewOrchestrator(db)
                result = await orchestrator.generate(
                    ReviewGenerationRequest(
                        review_id=review_id,
                        workspace_id=workspace_id,
                        service_id=service_id,
                        week_start=review.review_week_start,
                        week_end=review.review_week_end,
                    )
                )

                if result.success:
                    logger.info(
                        f"Health review {review_id} completed successfully "
                        f"in {result.generation_duration_seconds}s"
                    )
                else:
                    logger.error(
                        f"Health review {review_id} failed: {result.error_message}"
                    )

            except Exception as e:
                logger.exception(f"Error processing health review {review_id}: {e}")

                # Try to mark review as failed
                try:
                    review = await db.get(ServiceReview, review_id)
                    if review and review.status != ReviewStatus.FAILED:
                        review.status = ReviewStatus.FAILED
                        review.error_message = str(e)
                        review.generated_at = datetime.now(timezone.utc)
                        await db.commit()
                except Exception:
                    logger.exception(
                        f"Failed to update review {review_id} status to FAILED"
                    )
            finally:
                clear_job_id()
                clear_sentry_context()


async def publish_health_review_job(
    review_id: str,
    workspace_id: str,
    service_id: str,
    delay_seconds: int = 0,
) -> bool:
    """
    Publish a health review job to the SQS queue.

    Args:
        review_id: The ID of the ServiceReview record
        workspace_id: The workspace ID
        service_id: The service ID
        delay_seconds: Optional delay before the message becomes visible

    Returns:
        True if message was sent successfully, False otherwise
    """
    message = {
        "review_id": review_id,
        "workspace_id": workspace_id,
        "service_id": service_id,
    }

    return await health_review_sqs_client.send_message(
        message_body=message,
        delay_seconds=delay_seconds,
    )


# Entry point for running the worker directly
async def main():
    """Run the health review worker."""
    worker = HealthReviewWorker()

    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        asyncio.create_task(worker.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    await worker.start()

    # Keep running until stopped
    while worker.running:
        await asyncio.sleep(1)


if __name__ == "__main__":
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    asyncio.run(main())
