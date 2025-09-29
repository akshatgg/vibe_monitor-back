import hmac
import hashlib
import logging
from typing import Dict, Any

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.slack.schemas import SlackEventPayload, SlackWebhookPayload

logger = logging.getLogger(__name__)

class SlackEventService:
    @staticmethod
    async def verify_slack_request(
        slack_signature: str, 
        slack_request_timestamp: str, 
        request_body: str
    ) -> bool:
        """
        Verify Slack request signature for security
        """
        if not (settings.SLACK_SIGNING_SECRET and slack_signature and slack_request_timestamp):
            logger.warning("Missing Slack verification parameters")
            return False

        base_string = f"v0:{slack_request_timestamp}:{request_body}"
        signature = 'v0=' + hmac.new(
            key=settings.SLACK_SIGNING_SECRET.encode('utf-8'),
            msg=base_string.encode('utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(signature, slack_signature)

    @staticmethod
    async def handle_slack_event(payload: SlackEventPayload) -> Dict[str, Any]:
        """
        Process Slack event and trigger external webhook
        """
        try:
            # Extract message context
            event_context = payload.extract_message_context()
            logger.info(f"Received Slack event: {event_context}")

            # Prepare webhook payload
            webhook_payload = SlackWebhookPayload(event_context=event_context)

            # Call external webhook if configured
            if settings.SLACK_WEBHOOK_URL:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        settings.SLACK_WEBHOOK_URL, 
                        json=webhook_payload.to_webhook_payload(),
                        timeout=10.0
                    )
                    response.raise_for_status()
                    logger.info("Successfully sent payload to webhook")

            return {
                "status": "success", 
                "message": "Event processed successfully",
                "payload": event_context
            }

        except Exception as e:
            logger.error(f"Error processing Slack event: {e}")
            raise HTTPException(status_code=500, detail=str(e))

slack_event_service = SlackEventService()