import hmac
import hashlib
import logging
import uuid
import re
import time
from typing import Optional
from datetime import datetime, timezone
from collections import OrderedDict
from threading import Lock

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.utils.retry_decorator import retry_external_api
from app.slack.schemas import (
    SlackEventPayload,
    SlackInstallationCreate,
    SlackInstallationResponse,
)
from app.models import SlackInstallation
from app.models import Job, JobStatus
from app.slack.alert_detector import alert_detector


from app.utils.token_processor import token_processor
from app.utils.rate_limiter import check_rate_limit, ResourceType


logger = logging.getLogger(__name__)


# Event deduplication cache to prevent infinite loops
# Maps event_id -> timestamp of when it was first processed
# TTL: 5 minutes (longer than Slack's retry window of 1-2 minutes)
class EventDeduplicationCache:
    """Thread-safe in-memory cache for event deduplication with TTL"""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._lock = Lock()

    def is_duplicate(self, event_id: str) -> bool:
        """Check if event was already processed. Returns True if duplicate."""
        with self._lock:
            current_time = time.time()

            # Check if event exists and is still valid
            if event_id in self._cache:
                timestamp = self._cache[event_id]
                if current_time - timestamp <= self.ttl_seconds:
                    logger.warning(
                        f"Duplicate event detected: {event_id} "
                        f"(originally processed {current_time - timestamp:.1f}s ago)"
                    )
                    return True
                # Expired - remove and treat as new
                del self._cache[event_id]

            return False

    def mark_processed(self, event_id: str) -> None:
        """Mark event as processed"""
        with self._lock:
            self._cache[event_id] = time.time()

            # Cleanup old entries if cache gets too large
            if len(self._cache) > 1000:
                self._cleanup()

    def _cleanup(self) -> None:
        """Remove expired entries"""
        current_time = time.time()
        expired = [
            eid for eid, ts in self._cache.items()
            if current_time - ts > self.ttl_seconds
        ]
        for eid in expired:
            del self._cache[eid]
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired events")


# Global deduplication cache
_event_cache = EventDeduplicationCache(ttl_seconds=300)


class SlackEventService:
    @staticmethod
    async def verify_slack_request(
        slack_signature: str, slack_request_timestamp: str, request_body: str
    ) -> bool:
        """
        Verify Slack request signature for security
        """
        if not (
            settings.SLACK_SIGNING_SECRET
            and slack_signature
            and slack_request_timestamp
        ):
            logger.warning("Missing Slack verification parameters")
            return False

        base_string = f"v0:{slack_request_timestamp}:{request_body}"
        signature = (
            "v0="
            + hmac.new(
                key=settings.SLACK_SIGNING_SECRET.encode("utf-8"),
                msg=base_string.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
        )

        return hmac.compare_digest(signature, slack_signature)

    @staticmethod
    async def handle_slack_event(payload: SlackEventPayload) -> dict:
        """
        Process Slack event and respond to user
        Handles both explicit mentions (@bot) and automatic alert detection
        """
        try:
            # CRITICAL: Check for duplicate events first to prevent infinite loops
            # Slack may retry events, and our own bot messages trigger new events
            if _event_cache.is_duplicate(payload.event_id):
                logger.info(f"Skipping duplicate event: {payload.event_id}")
                return {
                    "status": "ignored",
                    "message": "Duplicate event (already processed)"
                }

            # Mark event as being processed
            _event_cache.mark_processed(payload.event_id)

            # Extract message context
            event_context = payload.extract_message_context()
            logger.info(f"Received Slack event: {event_context}")

            team_id = event_context.get("team_id")
            channel_id = event_context.get("channel_id")
            event_type = payload.event.get("type")
            event_subtype = payload.event.get("subtype")

            # Get bot user ID for this team
            slack_installation = await SlackEventService.get_installation(team_id)
            bot_user_id = slack_installation.bot_user_id if slack_installation else None

            # Check if this is a member joined channel event
            if event_subtype == "channel_join":
                # Retrieve the Slack installation for this team
                slack_installation = await SlackEventService.get_installation(team_id)
                if not slack_installation:
                    logger.warning(f"No Slack installation found for team {team_id}")
                    return {
                        "status": "ignored",
                        "message": "No Slack installation found",
                    }
                if payload.event.get("user") == slack_installation.bot_user_id:
                    welcome_message = (
                        "👋 Hey everyone!\n\n\n"
                        "I'm your friendly coding assistant debugging assistant bot 🤖 — here to help you debug issues, investigate alerts, and understand tech concepts understand how to tackle them better.\n"
                        "Here's how you can make the most of me 👇\n\n\n"
                        "🧩  1️⃣ Always tag me to talk to me\n"
                        "       I only respond when you mention @bot on an alert thread.\n"
                        "       Example: `@bot please help me investigate this error message.`\n\n\n"
                        "⚙️  2️⃣ What can I help with?\n"
                        "       Anything related to code, errors, or general understanding.\n"
                        "       Example scenarios:\n"
                        "       An alert pops up in this channel → tag me in the thread:\n"
                        "       `@bot please investigate this issue.`\n"
                        "       You encounter an error somewhere else → tag me with context:\n"
                        "       Hey @bot can you investigate this error?\n"
                        "       `requests.exceptions.Timeout: HTTP request to api.weatherdata.com timed out after 30 seconds`\n\n\n"
                        "💬  3️⃣ Keep the context clear for best results\n"
                        "       Try to include logs, stack traces, or what was happening when the issue occurred.\n"
                        "       Avoid vague lines like:\n"
                        '       `"Something went wrong."`\n'
                        '       `"Process failed unexpectedly."`\n'
                        "       The more specific you are, the faster and more accurate I'll be 💡\n\n\n"
                        "🧠  4️⃣ I remember context per thread!\n"
                        "       If we're chatting under a thread, I'll remember our earlier messages there.\n"
                        "       That means you can continue the same investigation without repeating yourself 🙌\n\n\n"
                        "⚡  5️⃣ I might take a few seconds to reply\n"
                        "       Sometimes I'm fetching data, analyzing logs, or thinking deeply 🧘 — give me a moment and I'll get back with my findings.\n\n\n"
                        "💡 Bonus:\n"
                        "   You can also ask me conceptual stuff like:\n"
                        "   `@bot what's the difference between multiprocessing and threading in Python?`\n"
                        "   Let's debug smart and fast together 🐞🔥"
                    )

                await SlackEventService.send_message(
                    team_id=team_id, channel=channel_id, text=welcome_message
                )

            # Handle app_mention events (explicit @bot mentions)
            if event_type == "app_mention":
                user_message_ex = event_context.get("text", "").strip()

                # Process the message and generate response
                bot_response = await SlackEventService.process_user_message(
                    user_message=user_message_ex,
                    event_context=event_context,
                    is_explicit_mention=True
                )
                clean_message = re.sub(r"<@[A-Z0-9]+>", "", user_message_ex).strip()

                if clean_message.lower() in ["help", "status", "health"]:
                    thread_ts = event_context.get("thread_ts")
                else:
                    thread_ts = event_context.get("thread_ts") or event_context.get(
                        "timestamp"
                    )

                await SlackEventService.send_message(
                    team_id=team_id,
                    channel=channel_id,
                    text=bot_response,
                    thread_ts=thread_ts,
                )

            # Handle regular message events (automatic alert detection)
            elif event_type == "message" and not event_subtype:
                # Only ignore our own bot's messages, not other bots (like Sentry, Grafana)
                if payload.event.get("user") == bot_user_id:
                    logger.debug("Ignoring our bot's own message")
                    return {"status": "ignored", "message": "Bot's own message"}

                # Check if this message is an alert
                message_text = event_context.get("text", "").strip()
                should_respond, reason = alert_detector.should_auto_respond(
                    message_text=message_text,
                    bot_user_id=bot_user_id,
                    channel_id=channel_id,
                    event=payload.event,
                )

                if should_respond:
                    logger.info(f"Auto-responding to alert in channel {channel_id}: {reason}")

                    # Extract alert information
                    alert_info = alert_detector.extract_alert_info(message_text, event=payload.event)

                    # Process as RCA request
                    bot_response = await SlackEventService.process_user_message(
                        user_message=message_text,
                        event_context=event_context,
                        is_explicit_mention=False,
                        alert_info=alert_info
                    )

                    # Reply in thread to keep channel clean
                    thread_ts = event_context.get("thread_ts") or event_context.get("timestamp")

                    await SlackEventService.send_message(
                        team_id=team_id,
                        channel=channel_id,
                        text=bot_response,
                        thread_ts=thread_ts,
                    )
                else:
                    logger.debug(f"Not auto-responding: {reason}")
                    return {"status": "ignored", "message": reason}

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
                "payload": event_context,
            }

        except Exception as e:
            logger.error(f"Error processing Slack event: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @staticmethod
    async def process_user_message(
        user_message: str,
        event_context: dict,
        is_explicit_mention: bool = True,
        alert_info: dict = None
    ) -> str:
        """
        Process user's message and generate a response

        Args:
            user_message: The message text
            event_context: Slack event context
            is_explicit_mention: True if user explicitly mentioned bot, False for auto-detected alerts
            alert_info: Dictionary with alert metadata (platform, severity, etc.) if auto-detected

        This handles:
        - Command parsing (help, status, etc.)
        - RCA request creation for alerts and user queries
        - Business logic
        """
        from app.services.sqs.client import sqs_client

        user_id = event_context.get("user_id")
        channel_id = event_context.get("channel_id")
        timestamp = event_context.get("timestamp")
        team_id = event_context.get("team_id")
        thread_ts = event_context.get("thread_ts") or event_context.get("timestamp")

        # Remove bot mention from message to get clean text
        clean_message = re.sub(r"<@[A-Z0-9]+>", "", user_message).strip()

        # For automatic alert detection, provide different initial response
        if not is_explicit_mention and alert_info:
            platform = alert_info.get("platform", "monitoring tool")
            severity = alert_info.get("severity", "")
            severity_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🟢"
            }.get(severity, "🔵")

            logger.info(
                f"Processing auto-detected {platform} alert "
                f"(severity: {severity or 'unknown'}) in channel {channel_id}"
            )
        else:
            logger.info(f"Processing explicit mention from user {user_id}: '{clean_message}'")

        # Simple command handling (only for explicit mentions)
        if is_explicit_mention:
            if not clean_message or clean_message.lower() in ["hi", "hello", "hey"]:
                return f"👋 Hi <@{user_id}>! How can I help you today? Ask me anything about your services, logs, or metrics!"

            elif clean_message.lower() in ["help", "commands"]:
                return (
                    f"Hi <@{user_id}>! Here's what I can do:\n\n"
                    "🔍 *AI-Powered Root Cause Analysis*\n"
                    "Ask me questions about your services and I'll investigate logs and metrics:\n"
                    '• _"Why is my xyz service slow?"_\n'
                    '• _"Check errors in api-gateway service"_\n'
                    '• _"What\'s causing high CPU on auth-service?"_\n'
                    '• _"Investigate database timeouts"_\n\n'
                    "📋 *Commands*\n"
                    "• `help` - Show this message\n"
                    "• `status` - Check bot health\n\n"
                    "💡 *NEW: Automatic Alert Monitoring*\n"
                    "I now automatically detect and investigate alerts from Grafana, Sentry, and other tools!\n"
                    "No need to tag me - I'll jump in when alerts appear 🚨\n\n"
                    "I use AI to analyze your observability data and provide actionable insights! 🚀"
                )

            elif clean_message.lower() == "status":
                return (
                    f"✅ System Status:\n\n"
                    f"• Bot: Online and running\n"
                    f"• AI Agent: Ready (Groq LLM)\n"
                    f"• Auto Alert Detection: Enabled ✨\n"
                    f"• Channel: <#{channel_id}>\n"
                    f"• Your User ID: {user_id}\n"
                    f"• Message received at: {timestamp}"
                )

        # Process RCA query (works for both mentions and auto-detected alerts)
        if True:  # Always process as RCA for non-command messages
            # This looks like an RCA query - create Job record and enqueue to SQS
            logger.info(f"Creating RCA job for query: '{clean_message}'")

            # Generate job ID
            job_id = str(uuid.uuid4())

            try:
                # Create Job record in database
                async with AsyncSessionLocal() as db:
                    # Get slack integration ID and workspace_id from team_id
                    slack_integration = await SlackEventService.get_installation(
                        team_id
                    )
                    if not slack_integration:
                        logger.error(f"No Slack installation found for team {team_id}")
                        return (
                            f"❌ Sorry <@{user_id}>, your Slack workspace is not properly configured. "
                            f"Please reinstall the app or contact support."
                        )

                    if not slack_integration.workspace_id:
                        logger.error(
                            f"Slack installation {slack_integration.id} has no workspace_id"
                        )
                        return (
                            f"❌ Sorry <@{user_id}>, your Slack workspace is not linked to a VibeMonitor workspace. "
                            f"Please complete the setup or contact support."
                        )

                    slack_integration_id = slack_integration.id
                    workspace_id = slack_integration.workspace_id

                    # Check rate limit before creating job

                    try:
                        allowed, current_count, limit = await check_rate_limit(
                            session=db,
                            workspace_id=workspace_id,
                            resource_type=ResourceType.RCA_REQUEST,
                        )

                        if not allowed:
                            logger.warning(
                                f"RCA rate limit exceeded for workspace {workspace_id}: "
                                f"{current_count}/{limit}"
                            )
                            return (
                                f"⚠️ *Daily RCA Request Limit Reached*\n\n"
                                f"Your workspace has reached the daily limit of *{limit} RCA requests*.\n\n"
                                f"📅 Current usage: {current_count}/{limit}\n"
                                f"🔄 Limit resets: Tomorrow at midnight UTC\n\n"
                                f"Please try again tomorrow or contact support@vibemonitor.ai to increase your limits."
                            )

                        logger.info(
                            f"RCA rate limit check passed for workspace {workspace_id}: "
                            f"{current_count}/{limit}"
                        )

                    except ValueError as e:
                        logger.error(f"Rate limit check failed: {e}")
                        return (
                            f"❌ Sorry <@{user_id}>, there was an error checking your workspace limits. "
                            f"Please contact support."
                        )
                    except Exception as e:
                        logger.exception(f"Unexpected error in rate limit check: {e}")
                        # Fail open: allow the request but log the error
                        logger.warning(
                            f"Rate limit check failed for workspace {workspace_id}, "
                            f"allowing request to proceed"
                        )

                    # Create job record with alert info if auto-detected
                    job_context = {
                        "query": clean_message,
                        "user_id": user_id,
                        "team_id": team_id,
                        "is_explicit_mention": is_explicit_mention,
                    }

                    # Add alert metadata if this was auto-detected
                    if alert_info:
                        job_context["alert_info"] = alert_info
                        job_context["auto_detected"] = True

                    job = Job(
                        id=job_id,
                        vm_workspace_id=workspace_id,
                        slack_integration_id=slack_integration_id,
                        trigger_channel_id=channel_id,
                        trigger_thread_ts=thread_ts,
                        trigger_message_ts=timestamp,
                        status=JobStatus.QUEUED,
                        requested_context=job_context,
                    )
                    db.add(job)
                    await db.commit()
                    logger.info(f"✅ Job {job_id} created in database")

                # Send lightweight message to SQS (just job_id)
                success = await sqs_client.send_message({"job_id": job_id})

                if success:
                    logger.info(f"✅ Job {job_id} enqueued to SQS")

                    # Different responses for auto-detected alerts vs explicit mentions
                    if not is_explicit_mention and alert_info:
                        platform = alert_info.get("platform", "monitoring tool")
                        severity = alert_info.get("severity", "")
                        severity_emoji = {
                            "critical": "🔴",
                            "high": "🟠",
                            "medium": "🟡",
                            "low": "🟢"
                        }.get(severity, "🔵")

                        return (
                            f"{severity_emoji} *Alert Detected* {severity_emoji}\n\n"
                            f"📊 Source: {platform.title()}\n"
                            f"{f'⚠️ Severity: {severity.title()}' if severity else ''}\n\n"
                            f"🤖 sit back and relax, I'm investigating this alert...\n"
                            f"Analyzing logs, metrics, and recent changes. I'll provide my findings shortly."
                        )
                    else:
                        return (
                            f"🔍 Got it! I'm analyzing: *\"{clean_message[:100]}...\"*\n\n"
                            f"This may take a moment while I investigate logs and metrics. "
                            f"I'll reply here once I have the analysis ready."
                        )
                else:
                    logger.error(f"❌ Failed to enqueue job {job_id} to SQS")
                    # Mark job as failed since we couldn't enqueue it
                    async with AsyncSessionLocal() as db:
                        job = await db.get(Job, job_id)
                        if job:
                            job.status = JobStatus.FAILED
                            job.error_message = "Failed to enqueue to SQS"
                            await db.commit()

                    return (
                        f"❌ Sorry <@{user_id}>, I'm having trouble processing your request right now. "
                        f"Please try again in a moment."
                    )

            except Exception as e:
                logger.exception(f"❌ Error creating job: {e}")
                return (
                    f"❌ Sorry <@{user_id}>, I encountered an error while processing your request. "
                    f"Please try again in a moment."
                )

    @staticmethod
    async def store_installation(
        team_id: str,
        team_name: str,
        access_token: str,
        bot_user_id: str,
        scope: str,
        workspace_id: Optional[
            str
        ] = None,  # this is vibemonitor workspace id/ not yet configured
    ) -> SlackInstallationResponse:
        """
        Store Slack workspace installation details in PostgreSQL
        """

        try:
            access_token = token_processor.encrypt(access_token)
            logger.info("access token for slack installation encrypted successfully")
        except Exception as err:
            raise Exception(
                f"error encrypting access token while slack installation {err}"
            )

        async with AsyncSessionLocal() as db:
            try:
                # Check if installation already exists
                statement = select(SlackInstallation).where(
                    SlackInstallation.team_id == team_id
                )
                result = await db.execute(statement)
                existing = result.scalar_one_or_none()

                if existing:
                    # Update existing installation
                    existing.team_name = team_name
                    existing.access_token = access_token
                    existing.bot_user_id = bot_user_id
                    existing.scope = scope
                    existing.workspace_id = workspace_id
                    existing.updated_at = datetime.now(timezone.utc)

                    logger.info(f"Updated installation for {team_id} ({team_name})")
                    installation_db = existing
                else:
                    # Create new installation
                    installation_data = SlackInstallationCreate(
                        team_id=team_id,
                        team_name=team_name,
                        access_token=access_token,
                        bot_user_id=bot_user_id,
                        scope=scope,
                        workspace_id=workspace_id,
                    )

                    installation_db = SlackInstallation(
                        id=str(uuid.uuid4()), **installation_data.model_dump()
                    )
                    db.add(installation_db)
                    logger.info(f"Created new installation for {team_id} ({team_name})")

                await db.commit()
                await db.refresh(installation_db)

                return SlackInstallationResponse.model_validate(installation_db)

            except Exception as e:
                await db.rollback()
                logger.error(f"Error storing installation: {e}", exc_info=True)
                raise

    @staticmethod
    async def get_installation(team_id: str) -> Optional[SlackInstallationResponse]:
        """
        Retrieve Slack installation for a workspace from database
        """
        async with AsyncSessionLocal() as db:
            try:
                statement = select(SlackInstallation).where(
                    SlackInstallation.team_id == team_id
                )
                result = await db.execute(statement)
                installation_db = result.scalar_one_or_none()

                if not installation_db:
                    logger.warning(f"No installation found for team {team_id}")
                    return None

                return SlackInstallationResponse.model_validate(installation_db)

            except Exception as e:
                logger.error(f"Error retrieving installation: {e}", exc_info=True)
                return None

    @staticmethod
    async def send_message(
        team_id: str, channel: str, text: str, thread_ts: Optional[str] = None
    ) -> Optional[dict]:
        """
        Send a message to a Slack channel or thread

        Uses the stored access token for the workspace

        Args:
            team_id: Slack team/workspace ID
            channel: Channel ID to send message to
            text: Message text
            thread_ts: Thread timestamp - if provided, replies in thread; otherwise posts to channel

        Returns:
            Dict with 'ok' status and 'ts' (message timestamp) if successful, None if failed
        """
        installation = await SlackEventService.get_installation(team_id)

        if not installation:
            logger.error(f"No installation found for team {team_id}")
            return None

        if not installation.access_token:
            logger.error(f"No access token found for team {team_id}")
            return None

        try:
            access_token = token_processor.decrypt(installation.access_token)
            logger.info("Access token decrypted successfully for slack message")
        except Exception as err:
            logger.error(f"Error decrypting access token for team {team_id}: {err}")
            return None

        try:
            async with httpx.AsyncClient() as client:
                payload = {"channel": channel, "text": text}

                # Add thread_ts to reply in thread, if thread_ts is not provided, message will be posted to channel
                if thread_ts:
                    payload["thread_ts"] = thread_ts

                async for attempt in retry_external_api("Slack"):
                    with attempt:
                        response = await client.post(
                            f"{settings.SLACK_API_BASE_URL}/chat.postMessage",
                            headers={
                                "Authorization": f"Bearer {access_token}",
                                "Content-Type": "application/json",
                            },
                            json=payload,
                            timeout=10.0,
                        )
                        response.raise_for_status()

                        data = response.json()

                        if data.get("ok"):
                            logger.info(f"Message sent successfully to {channel}")
                            return {"ok": True, "ts": data.get("ts")}
                        else:
                            logger.error(f"Failed to send message: {data.get('error')}")
                            return None

        except Exception as e:
            logger.error(f"Error sending Slack message: {e}")
            return None

    @staticmethod
    async def update_message(
        team_id: str, channel: str, ts: str, text: str
    ) -> bool:
        """
        Update an existing Slack message

        Args:
            team_id: Slack team/workspace ID
            channel: Channel ID where the message is
            ts: Message timestamp to update
            text: New message text

        Returns:
            True if successful, False otherwise
        """
        installation = await SlackEventService.get_installation(team_id)

        if not installation:
            logger.error(f"No installation found for team {team_id}")
            return False

        if not installation.access_token:
            logger.error(f"No access token found for team {team_id}")
            return False

        try:
            access_token = token_processor.decrypt(installation.access_token)
            logger.info("Access token decrypted successfully for slack message update")
        except Exception as err:
            logger.error(f"Error decrypting access token for team {team_id}: {err}")
            return False

        try:
            async with httpx.AsyncClient() as client:
                payload = {"channel": channel, "ts": ts, "text": text}

                response = await client.post(
                    f"{settings.SLACK_API_BASE_URL}/chat.update",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=10.0,
                )

            data = response.json()

            if data.get("ok"):
                logger.info(f"Message updated successfully in {channel}")
                return True
            else:
                logger.error(f"Failed to update message: {data.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Error updating Slack message: {e}")
            return False


slack_event_service = SlackEventService()
