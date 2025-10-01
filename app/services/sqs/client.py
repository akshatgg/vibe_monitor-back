import asyncio
import json
import logging
from typing import Optional, Dict, Any
import aioboto3
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError, NoCredentialsError
from app.core.config import settings

logger = logging.getLogger(__name__)


class SQSClient:
    def __init__(self):
        self.queue_url = settings.SQS_QUEUE_URL
        self.region = settings.AWS_REGION
        self._session = None
        self._sqs = None

    async def _get_sqs_client(self):
        if self._sqs is None:
            self._session = aioboto3.Session()
            if not self.region:
                logger.error("AWS_REGION not configured")
                raise ValueError("AWS_REGION not configured")
            client_kwargs = {'region_name': self.region}

            # Add endpoint_url for LocalStack support in development
            if settings.AWS_ENDPOINT_URL and settings.ENVIRONMENT in ['dev', 'development']:
                client_kwargs['endpoint_url'] = settings.AWS_ENDPOINT_URL

            self._sqs = await self._session.client('sqs', **client_kwargs).__aenter__()
        return self._sqs

    async def send_message(self, message_body: Dict[str, Any], delay_seconds: int = 0) -> bool:
        try:
            if not self.queue_url:
                logger.error("SQS_QUEUE_URL not configured")
                return False

            sqs = await self._get_sqs_client()

            response = await sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(message_body),
                DelaySeconds=delay_seconds
            )

            logger.debug(f"Message sent to SQS: {response.get('MessageId')}")
            return True

        except (ClientError, EndpointConnectionError, NoCredentialsError, BotoCoreError):
            logger.exception("Failed to send message to SQS")
            return False
        except Exception:
            logger.exception("Unexpected error while sending message to SQS")
            return False

    async def receive_messages(self, max_messages: int = 1, wait_time: int = 20) -> list:
        try:
            if not self.queue_url:
                logger.error("SQS_QUEUE_URL not configured")
                return []

            sqs = await self._get_sqs_client()

            response = await sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time,
                MessageAttributeNames=['All']
            )

            messages = response.get('Messages', [])

            for message in messages:
                try:
                    message['ParsedBody'] = json.loads(message['Body'])
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse message body: {message['Body']}")
                    message['ParsedBody'] = None

            return messages

        except (ClientError, EndpointConnectionError, NoCredentialsError, BotoCoreError):
            logger.exception("Failed to receive messages from SQS")
            return []
        except Exception:
            logger.exception("Unexpected error while receiving messages from SQS")
            return []

    async def delete_message(self, receipt_handle: str) -> bool:
        try:
            if not self.queue_url:
                logger.error("SQS_QUEUE_URL not configured")
                return False

            sqs = await self._get_sqs_client()

            await sqs.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )

            logger.debug(f"Message deleted from SQS")
            return True

        except (ClientError, EndpointConnectionError, NoCredentialsError, BotoCoreError):
            logger.exception("Failed to delete message from SQS")
            return False
        except Exception:
            logger.exception("Unexpected error while deleting message from SQS")
            return False

    async def close(self):
        if self._sqs:
            await self._sqs.__aexit__(None, None, None)
            self._sqs = None
        # aioboto3 Session doesn't need explicit close
        self._session = None


sqs_client = SQSClient()