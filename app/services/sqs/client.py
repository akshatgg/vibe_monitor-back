import json
import logging
from typing import Dict, Any
import aioboto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class SQSClient:
    def __init__(self):
        """
        Initializes an SQSClient instance.

        This method sets the initial values for the `queue_url` and `region` attributes based on the application settings. It also initializes the `_session` and `_sqs` attributes to `None`, which will be lazily initialized later when the `_get_sqs_client` method is called.

        Parameters:
            None

        Returns:
            None
        """
        self.queue_url = settings.SQS_QUEUE_URL
        self.region = settings.AWS_REGION
        self._session = None
        self._sqs = None

    async def _get_sqs_client(self):
        """
        Ensure an initialized aioboto3 SQS client is available and return it.

        Initializes and caches an aioboto3 SQS client using the configured AWS region and, when running in development with an endpoint configured, an explicit endpoint URL. Raises ValueError if AWS region is not configured.

        Returns:
            sqs_client: The initialized aioboto3 SQS client instance.
        """
        if self._sqs is None:
            self._session = aioboto3.Session()
            if not self.region:
                logger.error("AWS_REGION not configured")
                raise ValueError("AWS_REGION not configured")
            client_kwargs = {"region_name": self.region}

            # Add endpoint_url for LocalStack support in development
            if settings.AWS_ENDPOINT_URL and settings.ENVIRONMENT in [
                "dev",
                "development",
            ]:
                client_kwargs["endpoint_url"] = settings.AWS_ENDPOINT_URL

            self._sqs = await self._session.client("sqs", **client_kwargs).__aenter__()
        return self._sqs

    async def send_message(
        self, message_body: Dict[str, Any], delay_seconds: int = 0
    ) -> bool:
        """
        Send a JSON-serializable message to the configured SQS queue.

        Parameters:
            message_body (Dict[str, Any]): The payload to serialize to JSON and send as the SQS message body.
            delay_seconds (int): Number of seconds to delay message delivery.

        Returns:
            True if the message was accepted by SQS, False otherwise.
        """
        try:
            if not self.queue_url:
                logger.error("SQS_QUEUE_URL not configured")
                return False

            sqs = await self._get_sqs_client()

            response = await sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(message_body),
                DelaySeconds=delay_seconds,
            )

            logger.debug(f"Message sent to SQS: {response.get('MessageId')}")
            return True

        except (
            ClientError,
            EndpointConnectionError,
            NoCredentialsError,
            BotoCoreError,
        ):
            logger.exception("Failed to send message to SQS")
            return False
        except Exception:
            logger.exception("Unexpected error while sending message to SQS")
            return False

    async def receive_messages(
        self, max_messages: int = 1, wait_time: int = 20
    ) -> list:
        """
        Retrieve up to `max_messages` from the configured SQS queue using long polling and attach a parsed JSON body.

        Parameters:
            max_messages (int): Maximum number of messages to request (1–10, per SQS limits).
            wait_time (int): Long-poll wait time in seconds (0–20); controls how long the call waits for messages.

        Returns:
            list: A list of message dicts as returned by SQS. Each message may include a `ParsedBody` key containing the JSON-decoded `Body` or `None` if parsing failed. Returns an empty list if the queue URL is not configured or on error.
        """
        try:
            if not self.queue_url:
                logger.error("SQS_QUEUE_URL not configured")
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
            logger.exception("Failed to receive messages from SQS")
            return []
        except Exception:
            logger.exception("Unexpected error while receiving messages from SQS")
            return []

    async def delete_message(self, receipt_handle: str) -> bool:
        """
        Delete a message from the configured SQS queue using its receipt handle.

        If the SQS queue URL is not configured or an error occurs while deleting, the method returns False.

        Parameters:
            receipt_handle (str): The receipt handle that identifies the message to delete from the queue.

        Returns:
            bool: `True` if the message was successfully deleted, `False` otherwise.
        """
        try:
            if not self.queue_url:
                logger.error("SQS_QUEUE_URL not configured")
                return False

            sqs = await self._get_sqs_client()

            await sqs.delete_message(
                QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
            )

            logger.debug("Message deleted from SQS")
            return True

        except (
            ClientError,
            EndpointConnectionError,
            NoCredentialsError,
            BotoCoreError,
        ):
            logger.exception("Failed to delete message from SQS")
            return False
        except Exception:
            logger.exception("Unexpected error while deleting message from SQS")
            return False

    async def close(self):
        """
        Close the internal SQS client and clear stored session state.

        If an active SQS client exists, exits its asynchronous context manager and clears the client reference. Clears the stored session reference (the aioboto3 Session is not explicitly closed).
        """
        if self._sqs:
            await self._sqs.__aexit__(None, None, None)
            self._sqs = None
        # aioboto3 Session doesn't need explicit close
        self._session = None


sqs_client = SQSClient()
