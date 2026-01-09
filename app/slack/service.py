import hashlib
import hmac
import logging
import re
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.chat.service import ChatService
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.otel_metrics import JOB_METRICS
from app.integrations.health_checks import check_slack_health
from app.integrations.service import get_workspace_integrations
from app.models import (
    Integration,
    Job,
    JobSource,
    JobStatus,
    SlackInstallation,
    TurnStatus,
)
from app.security.llm_guard import llm_guard
from app.slack.alert_detector import alert_detector
from app.slack.schemas import (
    SlackEventPayload,
    SlackInstallationCreate,
    SlackInstallationResponse,
)
from app.utils.rate_limiter import ResourceType, check_rate_limit_with_byollm_bypass
from app.utils.retry_decorator import retry_external_api
from app.utils.token_processor import token_processor

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
            eid
            for eid, ts in self._cache.items()
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
                    "message": "Duplicate event (already processed)",
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
                logger.info(f"Received app_mention with text: '{user_message_ex}'")

                # Process the message and generate response
                bot_response = await SlackEventService.process_user_message(
                    user_message=user_message_ex,
                    event_context=event_context,
                    is_explicit_mention=True,
                )
                clean_message = re.sub(
                    settings.SLACK_USER_MENTION_PATTERN, "", user_message_ex
                ).strip()

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
                    logger.info(
                        f"Auto-responding to alert in channel {channel_id}: {reason}"
                    )

                    # Extract alert information
                    alert_info = alert_detector.extract_alert_info(
                        message_text, event=payload.event
                    )

                    # Process as RCA request
                    bot_response = await SlackEventService.process_user_message(
                        user_message=message_text,
                        event_context=event_context,
                        is_explicit_mention=False,
                        alert_info=alert_info,
                    )

                    # Reply in thread to keep channel clean
                    thread_ts = event_context.get("thread_ts") or event_context.get(
                        "timestamp"
                    )

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
        alert_info: dict = None,
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
        clean_message = re.sub(
            settings.SLACK_USER_MENTION_PATTERN, "", user_message
        ).strip()

        # Check if this is an image-only message
        files = event_context.get("files", [])
        has_images = any(f.get("mimetype", "").startswith("image/") for f in files)

        # If no text but has images, set default message
        if not clean_message and has_images:
            clean_message = (
                "Please analyze this image/screenshot for any errors or issues."
            )
            logger.info("Image-only message detected, using default query text")

        # For automatic alert detection, provide different initial response
        if not is_explicit_mention and alert_info:
            platform = alert_info.get("platform", "monitoring tool")
            severity = alert_info.get("severity", "")
            severity_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🟢",
            }.get(severity, "🔵")

            logger.info(
                f"Processing auto-detected {platform} alert "
                f"(severity: {severity or 'unknown'}) in channel {channel_id}"
            )
        else:
            logger.info(
                f"Processing explicit mention from user {user_id}: '{clean_message}'"
            )

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

        # ═══════════════════════════════════════════════════════════════
        # SECURITY: LLM Guard - Validate message for prompt injection
        # ═══════════════════════════════════════════════════════════════
        # Get Slack installation details for security event tracking
        slack_integration = await SlackEventService.get_installation(team_id)
        slack_integration_id = slack_integration.id if slack_integration else None
        workspace_id = slack_integration.workspace_id if slack_integration else None

        logger.info(
            f"[SECURITY] Validating message with LLM Guard: '{clean_message[:100]}...'"
        )
        guard_result = await llm_guard.validate_message(
            user_message=clean_message,
            context=f"Slack message from user {user_id} in channel {channel_id}",
            workspace_id=workspace_id,
            slack_integration_id=slack_integration_id,
            slack_user_id=user_id,
        )

        if guard_result["blocked"]:
            # Log the security incident
            logger.warning(
                f"Message BLOCKED by LLM Guard - "
                f"User: {user_id}, Channel: {channel_id}, "
                f"Reason: {guard_result['reason']}, "
                f"LLM Response: {guard_result['llm_response']}"
            )

            # Return user-friendly error message
            return (
                f"⚠️ Sorry <@{user_id}>, your message was blocked due to security concerns.\n\n"
                f"If you believe this is a mistake, please rephrase your message and try again, "
                f"or contact support@vibemonitor.ai for assistance."
            )

        logger.info("[SECURITY] Message PASSED LLM Guard validation ✓")

        # Process RCA query (works for both mentions and auto-detected alerts)
        if True:  # Always process as RCA for non-command messages
            # This looks like an RCA query - create Job record and enqueue to SQS
            logger.info(f"Creating RCA job for query: '{clean_message}'")

            # Check if this is a thread reply and fetch conversation history
            thread_history = None
            original_thread_ts = event_context.get("thread_ts")

            if original_thread_ts:
                logger.info(
                    f"Detected thread reply with thread_ts: {original_thread_ts}. Fetching conversation history..."
                )
                thread_history = await SlackEventService.get_thread_history(
                    team_id=team_id,
                    channel=channel_id,
                    thread_ts=original_thread_ts,
                    exclude_ts=timestamp,  # Exclude current message to avoid duplicate context
                )

                if thread_history:
                    logger.info(
                        f"Successfully retrieved {len(thread_history)} messages from thread history"
                    )
                else:
                    logger.warning(
                        f"Failed to retrieve thread history for thread_ts: {original_thread_ts}"
                    )
            else:
                logger.info(
                    "No thread_ts detected - this is a new conversation (not a thread reply)"
                )

            # Generate job ID
            job_id = str(uuid.uuid4())

            try:
                # Create Job record in database
                async with AsyncSessionLocal() as db:
                    # Verify we have slack integration (already fetched earlier for LLM guard)
                    if not slack_integration:
                        logger.error(f"No Slack installation found for team {team_id}")
                        return (
                            f"❌ Sorry <@{user_id}>, your Slack workspace is not properly configured. "
                            f"Please reinstall the app or contact support."
                        )

                    if not workspace_id:
                        logger.error(
                            f"Slack installation {slack_integration_id} has no workspace_id"
                        )
                        return (
                            f"❌ Sorry <@{user_id}>, your Slack workspace is not linked to a VibeMonitor workspace. "
                            f"Please complete the setup or contact support."
                        )

                    # ═══════════════════════════════════════════════════════════════
                    # PRE-CHECK: Verify GitHub integration exists (required for RCA)
                    # ═══════════════════════════════════════════════════════════════
                    all_integrations = await get_workspace_integrations(
                        workspace_id, db
                    )
                    github_integration = next(
                        (i for i in all_integrations if i.provider == "github"), None
                    )

                    if not github_integration:
                        logger.warning(
                            f"GitHub integration not found for workspace {workspace_id}"
                        )
                        return (
                            "⚠️ *Github integration is not configured*\n\n"
                            "The Github integration is required for RCA analysis "
                            "but has not been set up for this workspace.\n\n"
                            "*To resolve this:*\n"
                            "• Connect your Github account in the dashboard\n"
                            "• Ensure the integration is properly configured"
                        )

                    # Check rate limit before creating job (BYOLLM users bypass rate limiting)

                    try:
                        (
                            allowed,
                            current_count,
                            limit,
                        ) = await check_rate_limit_with_byollm_bypass(
                            session=db,
                            workspace_id=workspace_id,
                            resource_type=ResourceType.RCA_REQUEST,
                        )

                        if not allowed:
                            from app.core.otel_metrics import SECURITY_METRICS
                            SECURITY_METRICS["rate_limit_exceeded_total"].add(
                                1,
                                {
                                    "resource_type": ResourceType.SLACK_MESSAGE,
                                },
                            )

                            logger.warning(
                                f"RCA rate limit exceeded for workspace {workspace_id}: "
                                f"{current_count}/{limit}"
                            )
                            return (
                                f"⚠️ *Daily RCA Request Limit Reached*\n\n"
                                f"Your workspace has reached the daily limit of *{limit} RCA requests*.\n\n"
                                f"📅 Current usage: {current_count}/{limit}\n"
                                f"🔄 Limit resets: Tomorrow at midnight UTC\n\n"
                                f"💡 *Tip:* Configure your own LLM (OpenAI, Azure, or Gemini) to remove limits!\n"
                                f"Visit your workspace settings or contact support@vibemonitor.ai for help."
                            )

                        # Log BYOLLM status (limit=-1 indicates unlimited)
                        if limit == -1:
                            logger.info(
                                f"BYOLLM workspace {workspace_id} - unlimited RCA requests"
                            )
                        else:
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

                    # ═══════════════════════════════════════════════════════════════
                    # Create ChatSession and ChatTurn (unified model for Slack + Web)
                    # ═══════════════════════════════════════════════════════════════
                    chat_service = ChatService(db)

                    # Get or create session for this Slack thread
                    session = await chat_service.get_or_create_slack_session(
                        workspace_id=workspace_id,
                        slack_team_id=team_id,
                        slack_channel_id=channel_id,
                        slack_thread_ts=thread_ts,
                        slack_user_id=user_id,
                        first_message=clean_message,
                    )

                    # Create turn for this message
                    turn = await chat_service.create_turn(
                        session=session,
                        user_message=clean_message,
                    )

                    # Build job context with alert info if auto-detected
                    job_context = {
                        "query": clean_message,
                        "user_id": user_id,
                        "team_id": team_id,
                        "turn_id": turn.id,  # Link to turn for feedback
                        "is_explicit_mention": is_explicit_mention,
                    }

                    # Add alert metadata if this was auto-detected
                    if alert_info:
                        job_context["alert_info"] = alert_info
                        job_context["auto_detected"] = True

                    # Add thread history to context if available
                    if thread_history:
                        job_context["thread_history"] = thread_history
                        logger.info(
                            f"Added {len(thread_history)} thread messages to job context"
                        )

                    # Add files (images) to context if present
                    files = event_context.get("files", [])
                    if files:
                        # Filter for image files only with proper validation
                        image_files = []
                        for f in files:
                            mimetype = f.get("mimetype", "")
                            url_private = f.get("url_private")

                            # Validate image file has required fields
                            if mimetype.startswith("image/"):
                                if url_private:
                                    image_files.append(f)
                                else:
                                    logger.warning(
                                        f"Skipping image file '{f.get('name', 'unknown')}' - "
                                        f"missing url_private field"
                                    )

                        if image_files:
                            job_context["files"] = image_files
                            job_context["has_images"] = True
                            logger.info(
                                f"Added {len(image_files)} validated image(s) to job context - will use Gemini for processing"
                            )
                        elif files:
                            logger.warning(
                                f"Found {len(files)} file(s) but none were valid images with required fields"
                            )

                    # Create job linked to turn
                    job = Job(
                        id=job_id,
                        vm_workspace_id=workspace_id,
                        source=JobSource.SLACK,
                        slack_integration_id=slack_integration_id,
                        trigger_channel_id=channel_id,
                        trigger_thread_ts=thread_ts,
                        trigger_message_ts=timestamp,
                        status=JobStatus.QUEUED,
                        requested_context=job_context,
                    )
                    db.add(job)

                    # Link job to turn and update turn status
                    turn.job_id = job_id
                    turn.status = TurnStatus.PROCESSING

                    await db.commit()

                    JOB_METRICS["jobs_created_total"].add(
                        1,
                        {
                            "job_source": job.source.value,
                        },
                    )

                    logger.info(
                        f"✅ Session {session.id}, Turn {turn.id}, Job {job_id} created"
                    )

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
                            "low": "🟢",
                        }.get(severity, "🔵")

                        return (
                            f"{severity_emoji} *Alert Detected* {severity_emoji}\n\n"
                            f"📊 Source: {platform.title()}\n"
                            f"{f'⚠️ Severity: {severity.title()}' if severity else ''}\n\n"
                            f"🤖 sit back and relax, I'm investigating this alert...\n"
                            f"Analyzing logs, metrics, and recent changes. I'll provide my findings shortly."
                        )
                    else:
                        return "👋 Let me help with that!"
                else:
                    logger.error(f"❌ Failed to enqueue job {job_id} to SQS")
                    # Mark job as failed since we couldn't enqueue it
                    async with AsyncSessionLocal() as db:
                        job = await db.get(Job, job_id)
                        if job:
                            job.status = JobStatus.FAILED
                            job.error_message = "Failed to enqueue to SQS"
                            await db.commit()

                            JOB_METRICS["jobs_failed_total"].add(
                                1,
                                {
                                    "job_source": job.source.value,
                                    "error_type": "SQSEnqueueError",
                                },
                            )

                    return (
                        f"❌ Sorry <@{user_id}>, I'm having trouble processing your request right now. "
                        f"Please try again in a moment."
                    )

            except Exception as e:
                logger.exception(f"❌ Error creating job: {e}")

                job_source_attr = (
                    getattr(job.source, "value", "unknown") if job else "unknown"
                )
                JOB_METRICS["jobs_failed_total"].add(
                    1,
                    {
                        "job_source": job_source_attr,
                        "error_type": "InternalError",
                    },
                )

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

                control_plane_integration = None

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

                    # Create or get existing Integration control plane record (if workspace_id is available)
                    control_plane_id = None
                    if workspace_id:
                        # Check if an integration already exists for this workspace + provider
                        existing_integration_stmt = select(Integration).where(
                            Integration.workspace_id == workspace_id,
                            Integration.provider == "slack",
                        )
                        existing_integration_result = await db.execute(
                            existing_integration_stmt
                        )
                        existing_integration = (
                            existing_integration_result.scalar_one_or_none()
                        )

                        if existing_integration:
                            # Use existing integration and update it
                            control_plane_id = existing_integration.id
                            control_plane_integration = existing_integration
                            control_plane_integration.status = "active"
                            control_plane_integration.updated_at = datetime.now(
                                timezone.utc
                            )
                            logger.info(
                                f"Reusing existing Slack integration {control_plane_id} for workspace {workspace_id}"
                            )
                        else:
                            # Create new integration
                            control_plane_id = str(uuid.uuid4())
                            control_plane_integration = Integration(
                                id=control_plane_id,
                                workspace_id=workspace_id,
                                provider="slack",
                                status="active",
                                created_at=datetime.now(timezone.utc),
                                updated_at=datetime.now(timezone.utc),
                            )
                            db.add(control_plane_integration)
                            await db.flush()  # Get ID without committing
                            logger.info(
                                f"Created new Slack integration {control_plane_id} for workspace {workspace_id}"
                            )

                    installation_db = SlackInstallation(
                        id=str(uuid.uuid4()),
                        integration_id=control_plane_id,  # Link to control plane (may be None)
                        **installation_data.model_dump(),
                    )
                    db.add(installation_db)
                    logger.info(f"Created new installation for {team_id} ({team_name})")

                await db.commit()
                await db.refresh(installation_db)

                # Run initial health check if control plane integration was created
                if control_plane_integration:
                    try:
                        health_status, error_message = await check_slack_health(
                            installation_db
                        )
                        control_plane_integration.health_status = health_status
                        control_plane_integration.last_verified_at = datetime.now(
                            timezone.utc
                        )
                        control_plane_integration.last_error = error_message
                        if health_status == "healthy":
                            control_plane_integration.status = "active"
                        elif health_status == "failed":
                            control_plane_integration.status = "error"
                        await db.commit()
                        logger.info(
                            f"Slack integration created with health_status={health_status}: "
                            f"team_id={team_id}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to run initial health check for Slack integration: {e}. "
                            f"Health status remains unset."
                        )

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
            logger.error(
                f"Failed to decrypt Slack access token for team {team_id}: {err}"
            )
            raise Exception("Failed to decrypt Slack credentials")

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
    async def get_thread_history(
        team_id: str, channel: str, thread_ts: str, exclude_ts: Optional[str] = None
    ) -> Optional[list]:
        """
        Fetch conversation history for a specific thread using Slack's conversations.replies API

        Args:
            team_id: Slack team/workspace ID
            channel: Channel ID where the thread exists
            thread_ts: Thread timestamp to fetch history for
            exclude_ts: Optional timestamp to exclude (typically the current triggering message)

        Returns:
            List of messages in the thread, or None if failed
        """
        # Validate required parameters
        if not channel or not isinstance(channel, str) or not channel.strip():
            logger.error("Invalid channel parameter: must be a non-empty string")
            return None

        if not thread_ts or not isinstance(thread_ts, str) or not thread_ts.strip():
            logger.error("Invalid thread_ts parameter: must be a non-empty string")
            return None

        installation = await SlackEventService.get_installation(team_id)

        if not installation:
            logger.error(f"No installation found for team {team_id}")
            return None

        if not installation.access_token:
            logger.error(f"No access token found for team {team_id}")
            return None

        try:
            access_token = token_processor.decrypt(installation.access_token)
            logger.info(
                "Access token decrypted successfully for fetching thread history"
            )
        except Exception as err:
            logger.error(
                f"Failed to decrypt Slack access token for team {team_id}: {err}"
            )
            raise Exception("Failed to decrypt Slack credentials")

        try:
            async with httpx.AsyncClient() as client:
                params = {"channel": channel, "ts": thread_ts}

                async for attempt in retry_external_api("Slack"):
                    with attempt:
                        response = await client.get(
                            f"{settings.SLACK_API_BASE_URL}/conversations.replies",
                            headers={
                                "Authorization": f"Bearer {access_token}",
                                "Content-Type": "application/json",
                            },
                            params=params,
                            timeout=10.0,
                        )
                        response.raise_for_status()

                        data = response.json()

                        if data.get("ok"):
                            messages = data.get("messages", [])

                            # Filter out the current triggering message to avoid duplicate context
                            if exclude_ts:
                                messages = [
                                    msg
                                    for msg in messages
                                    if msg.get("ts") != exclude_ts
                                ]

                            logger.info(
                                f"Successfully fetched {len(messages)} messages from thread {thread_ts}"
                            )
                            return messages
                        else:
                            logger.error(
                                f"Failed to fetch thread history: {data.get('error')}"
                            )
                            return None

        except Exception as e:
            logger.error(f"Error fetching Slack thread history: {e}")
            return None

    @staticmethod
    async def update_message(team_id: str, channel: str, ts: str, text: str) -> bool:
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
            logger.error(
                f"Failed to decrypt Slack access token for team {team_id}: {err}"
            )
            raise Exception("Failed to decrypt Slack credentials")

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

    @staticmethod
    async def send_message_with_feedback_button(
        team_id: str,
        channel: str,
        text: str,
        turn_id: str,
        thread_ts: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Send RCA response with a feedback button.

        Args:
            team_id: Slack team/workspace ID
            channel: Channel ID to send message to
            text: Message text (RCA response)
            turn_id: Turn ID to pass to feedback modal
            thread_ts: Thread timestamp for reply

        Returns:
            Dict with 'ok' status and 'ts' if successful, None if failed
        """
        installation = await SlackEventService.get_installation(team_id)

        if not installation or not installation.access_token:
            logger.error(f"No installation/token for team {team_id}")
            return None

        try:
            access_token = token_processor.decrypt(installation.access_token)
        except Exception as err:
            logger.error(f"Failed to decrypt token for team {team_id}: {err}")
            return None

        # Build message blocks with feedback buttons (comment option appears after feedback)
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "👍", "emoji": True},
                        "action_id": "feedback_thumbs_up",
                        "value": turn_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "👎", "emoji": True},
                        "action_id": "feedback_thumbs_down",
                        "value": turn_id,
                    },
                ],
            },
        ]

        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "channel": channel,
                    "text": text,  # Fallback for notifications
                    "blocks": blocks,
                }
                if thread_ts:
                    payload["thread_ts"] = thread_ts

                response = await client.post(
                    f"{settings.SLACK_API_BASE_URL}/chat.postMessage",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=10.0,
                )

                data = response.json()
                if data.get("ok"):
                    logger.info(f"Message with feedback buttons sent to {channel}")
                    return {"ok": True, "ts": data.get("ts")}
                else:
                    logger.error(f"Failed to send message: {data.get('error')}")
                    return None

        except Exception as e:
            logger.error(f"Error sending message with feedback button: {e}")
            return None

    @staticmethod
    async def update_message_with_feedback_confirmation(
        team_id: str,
        channel: str,
        message_ts: str,
        original_text: str,
        feedback_type: str,  # "thumbs_up", "thumbs_down", or "comment"
        turn_id: str,
    ) -> bool:
        """
        Update the original message to show feedback confirmation.

        Args:
            team_id: Slack team/workspace ID
            channel: Channel ID
            message_ts: Original message timestamp to update
            original_text: The original RCA response text
            feedback_type: Type of feedback given
            turn_id: Turn ID for the comment button

        Returns:
            True if successful, False otherwise
        """
        installation = await SlackEventService.get_installation(team_id)

        if not installation or not installation.access_token:
            logger.error(f"No installation/token for team {team_id}")
            return False

        try:
            access_token = token_processor.decrypt(installation.access_token)
        except Exception as err:
            logger.error(f"Failed to decrypt token for team {team_id}: {err}")
            return False

        # Build updated blocks with feedback confirmation
        if feedback_type == "thumbs_up":
            feedback_text = "✅ Thanks for the feedback! 👍"
            thumbs_up_style = "primary"
            thumbs_down_style = None
        elif feedback_type == "thumbs_down":
            feedback_text = "✅ Thanks for the feedback! 👎"
            thumbs_up_style = None
            thumbs_down_style = "primary"
        else:  # comment
            feedback_text = "✅ Thanks for your comment! 💬"
            thumbs_up_style = None
            thumbs_down_style = None

        # Build buttons with selected state
        thumbs_up_button = {
            "type": "button",
            "text": {"type": "plain_text", "text": "👍", "emoji": True},
            "action_id": "feedback_thumbs_up",
            "value": turn_id,
        }
        if thumbs_up_style:
            thumbs_up_button["style"] = thumbs_up_style

        thumbs_down_button = {
            "type": "button",
            "text": {"type": "plain_text", "text": "👎", "emoji": True},
            "action_id": "feedback_thumbs_down",
            "value": turn_id,
        }
        if thumbs_down_style:
            thumbs_down_button["style"] = thumbs_down_style

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": original_text}},
            {"type": "divider"},
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": feedback_text}],
            },
            {
                "type": "actions",
                "elements": [
                    thumbs_up_button,
                    thumbs_down_button,
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Add comment?",
                            "emoji": True,
                        },
                        "action_id": "feedback_with_comment",
                        "value": turn_id,
                    },
                ],
            },
        ]

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.SLACK_API_BASE_URL}/chat.update",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "channel": channel,
                        "ts": message_ts,
                        "text": original_text,
                        "blocks": blocks,
                    },
                    timeout=10.0,
                )

                data = response.json()
                if data.get("ok"):
                    logger.info(
                        f"Message updated with feedback confirmation: {feedback_type}"
                    )
                    return True
                else:
                    logger.error(f"Failed to update message: {data.get('error')}")
                    return False

        except Exception as e:
            logger.error(f"Error updating message with feedback confirmation: {e}")
            return False

    @staticmethod
    async def open_feedback_modal(
        team_id: str,
        trigger_id: str,
        turn_id: str,
    ) -> bool:
        """
        Open feedback modal in Slack for adding a comment.

        Args:
            team_id: Slack team/workspace ID
            trigger_id: Slack trigger ID from interaction
            turn_id: Turn ID to store in modal metadata

        Returns:
            True if successful, False otherwise
        """
        installation = await SlackEventService.get_installation(team_id)

        if not installation or not installation.access_token:
            return False

        try:
            access_token = token_processor.decrypt(installation.access_token)
        except Exception:
            return False

        # Build modal with comment input only (rating is done via buttons)
        modal = {
            "type": "modal",
            "callback_id": "feedback_submission",
            "private_metadata": turn_id,
            "title": {"type": "plain_text", "text": "Add Comment"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Share your thoughts on this response. Your feedback helps us improve! 🙏",
                    },
                },
                {
                    "type": "input",
                    "block_id": "comment_block",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "comment_input",
                        "multiline": True,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "What could be improved? What was helpful?",
                        },
                    },
                    "label": {"type": "plain_text", "text": "Your Comment"},
                },
            ],
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.SLACK_API_BASE_URL}/views.open",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={"trigger_id": trigger_id, "view": modal},
                    timeout=10.0,
                )

                data = response.json()
                if data.get("ok"):
                    logger.info(f"Feedback modal opened for turn {turn_id}")
                    return True
                else:
                    logger.error(f"Failed to open modal: {data.get('error')}")
                    return False

        except Exception as e:
            logger.error(f"Error opening feedback modal: {e}")
            return False


slack_event_service = SlackEventService()
