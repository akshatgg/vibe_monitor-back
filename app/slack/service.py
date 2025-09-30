import hmac
import hashlib
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.slack.schemas import SlackEventPayload, SlackWebhookPayload

logger = logging.getLogger(__name__)

# In-memory storage for Slack installations (for now)
# In production, you should store this in your PostgreSQL database
_slack_installations: Dict[str, Dict[str, Any]] = {}

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
        Process Slack event and respond to user
        """
        try:
            # Extract message context
            event_context = payload.extract_message_context()
            logger.info(f"Received Slack event: {event_context}")

            team_id = event_context.get("team_id")
            channel_id = event_context.get("channel_id")
            user_message = event_context.get("text", "").strip()

            # Process the message and generate response
            bot_response = await SlackEventService.process_user_message(
                user_message=user_message,
                event_context=event_context
            )

            # Send message back to Slack
            await SlackEventService.send_message(
                team_id=team_id,
                channel=channel_id,
                text=bot_response
            )

            # Call external webhook if configured (for additional processing)
            # if settings.SLACK_WEBHOOK_URL:
            #     webhook_payload = SlackWebhookPayload(event_context=event_context)
            #     async with httpx.AsyncClient() as client:
            #         response = await client.post(
            #             settings.SLACK_WEBHOOK_URL,
            #             json=webhook_payload.to_webhook_payload(),
            #             timeout=10.0
            #         )
            #         response.raise_for_status()
            #         logger.info("Successfully sent payload to webhook")

            return {
                "status": "success",
                "message": "Event processed and replied to user",
                "payload": event_context
            }

        except Exception as e:
            logger.error(f"Error processing Slack event: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @staticmethod
    async def process_user_message(
        user_message: str,
        event_context: Dict[str, Any]
    ) -> str:
        """
        Process user's message and generate a response

        This is where you add:
        - Command parsing (help, status, etc.)
        - AI integration (Groq, OpenAI, etc.)
        - Business logic
        """
        user_id = event_context.get("user_id")
        channel_id = event_context.get("channel_id")
        timestamp = event_context.get("timestamp")

        # Remove bot mention from message to get clean text
        clean_message = user_message
        # Remove <@BOTID> mention format
        import re
        clean_message = re.sub(r'<@[A-Z0-9]+>', '', clean_message).strip()

        logger.info(f"Processing message from user {user_id}: '{clean_message}'")

        # Simple command handling
        if not clean_message or clean_message.lower() in ['hi', 'hello', 'hey']:
            return f"👋 Hi <@{user_id}>! How can I help you today?"

        elif clean_message.lower() in ['help', 'commands']:
            return (
                f"Hi <@{user_id}>! Here's what I can do:\n\n"
                "• Just say `hi` or `hello` to greet me\n"
                "• Type `help` to see this message\n"
                "• Type `status` to check system status\n"
                "• Mention me with any message and I'll respond!\n\n"
                "More features coming soon! 🚀"
            )

        elif clean_message.lower() == 'status':
            return (
                f"✅ System Status:\n\n"
                f"• Bot: Online and running\n"
                f"• Channel: <#{channel_id}>\n"
                f"• Your User ID: {user_id}\n"
                f"• Message received at: {timestamp}"
            )

        else:
            # Default response for any other message
            return (
                f"👋 Hi <@{user_id}>! You said: *\"{clean_message}\"*\n\n"
                f"I received your message! Type `help` to see what I can do."
            )

    @staticmethod
    async def store_installation(
        team_id: str,
        team_name: str,
        access_token: str,
        bot_user_id: Optional[str],
        full_data: Dict[str, Any]
    ) -> None:
        """
        Store Slack workspace installation details

        TODO: In production, save this to PostgreSQL database
        For now, using in-memory storage for simplicity
        """
        installation_data = {
            "team_id": team_id,
            "team_name": team_name,
            "access_token": access_token,  # Use this to send messages to this workspace
            "bot_user_id": bot_user_id,
            "installed_at": datetime.utcnow().isoformat(),
            "scopes": full_data.get("scope", ""),
            "raw_response": full_data  # Store full OAuth response for debugging
        }

        # Store in memory (keyed by team_id)
        _slack_installations[team_id] = installation_data

        logger.info(f"Stored installation for team {team_id} ({team_name})")
        logger.debug(f"Installation data: {json.dumps(installation_data, indent=2)}")

        # TODO: Save to database
        # async with get_db() as db:
        #     slack_install = SlackInstallation(**installation_data)
        #     db.add(slack_install)
        #     await db.commit()

    @staticmethod
    async def get_installation(team_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve Slack installation for a workspace

        Returns the access token and other details needed to interact with Slack
        """
        installation = _slack_installations.get(team_id)

        if not installation:
            logger.warning(f"No installation found for team {team_id}")
            return None

        return installation

    @staticmethod
    async def get_all_installations() -> Dict[str, Dict[str, Any]]:
        """Get all stored installations (for debugging/admin)"""
        return _slack_installations.copy()

    @staticmethod
    async def send_message(team_id: str, channel: str, text: str) -> bool:
        """
        Send a message to a Slack channel

        Uses the stored access token for the workspace
        Falls back to SLACK_BOT_TOKEN if installation not found
        """
        installation = await SlackEventService.get_installation(team_id)

        if not installation:
            logger.warning(f"No installation found for team {team_id}")

            # Fallback to direct bot token for single workspace setup
            if settings.SLACK_BOT_TOKEN:
                logger.info("Using fallback SLACK_BOT_TOKEN")
                access_token = settings.SLACK_BOT_TOKEN
            else:
                logger.error(f"Cannot send message - no token available for team {team_id}")
                return False
        else:
            access_token = installation["access_token"]

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "channel": channel,
                        "text": text
                    },
                    timeout=10.0
                )

            data = response.json()

            if data.get("ok"):
                logger.info(f"Message sent successfully to {channel}")
                return True
            else:
                logger.error(f"Failed to send message: {data.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Error sending Slack message: {e}")
            return False

slack_event_service = SlackEventService()