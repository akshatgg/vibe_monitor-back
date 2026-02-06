"""
Custom LangChain callbacks for streaming RCA agent progress to Slack.

All sensitive data is masked before logging or sending to Slack.
"""

import ast
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, Optional

from langchain.callbacks.base import AsyncCallbackHandler

from app.core.config import settings
from app.core.otel_metrics import TOOL_METRICS
from app.services.rca.get_service_name.enums import TOOL_NAME_TO_MESSAGE
from app.slack.service import slack_event_service
from app.utils.data_masker import redact_query_for_log

logger = logging.getLogger(__name__)


def sanitize_error_for_user(error_msg: Optional[str]) -> str:
    """
    Sanitize error messages to remove sensitive internal details for user-facing messages.
    Always returns a generic user-friendly message - never exposes internal errors to customers.

    Args:
        error_msg: Raw error message that may contain sensitive details (can be None)

    Returns:
        User-friendly error message without internal details
    """
    # Validate input: ensure error_msg is a string
    if error_msg is None:
        error_msg = ""
    elif not isinstance(error_msg, str):
        error_msg = str(error_msg)

    # Log the original error for debugging (internal only)
    if error_msg:
        logger.error(f"❌ Analysis encountered an error: {error_msg}")

    # Always return a simple generic message - customers shouldn't see internal errors
    return "Something went wrong while processing your request"


def markdown_to_slack(text: str) -> str:
    """
    Convert Markdown formatting to Slack mrkdwn format.

    Slack uses different syntax than standard Markdown:
    - Bold: *text* (not **text**)
    - Italic: _text_ (not *text*)
    - Strikethrough: ~text~ (same)
    - Code: `text` (same)
    - Bullets: • (not * at line start)

    Args:
        text: Text with Markdown formatting

    Returns:
        Text with Slack mrkdwn formatting
    """
    # Convert **bold** to *bold*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # Convert markdown bullets (* item) to Slack bullets (• item)
    text = re.sub(r"^(\s*)\* ", r"\1• ", text, flags=re.MULTILINE)
    return text


class SlackProgressCallback(AsyncCallbackHandler):
    """
    Callback handler that sends agent thinking process to Slack in real-time
    Implements circuit breaker pattern to handle Slack API failures gracefully
    """

    def __init__(
        self,
        team_id: str,
        channel_id: str,
        thread_ts: Optional[str] = None,
        send_tool_output: bool = True,
        max_consecutive_failures: Optional[int] = None,
    ):
        """
        Initialize Slack progress callback

        Args:
            team_id: Slack team ID
            channel_id: Channel to send updates to
            thread_ts: Thread timestamp (for threaded replies)
            send_tool_output: Whether to send full tool outputs (can be verbose)
            max_consecutive_failures: Max failures before circuit breaker opens (uses config default if None)
        """
        self.team_id = team_id
        self.channel_id = channel_id
        self.thread_ts = thread_ts
        self.send_tool_output = send_tool_output
        self.step_counter = 0

        # Circuit breaker state
        self.consecutive_failures = 0
        self.max_consecutive_failures = (
            max_consecutive_failures
            if max_consecutive_failures is not None
            else settings.RCA_SLACK_MAX_CONSECUTIVE_FAILURES
        )
        self.circuit_open = False

        # Track last message for hourglass -> checkmark updates
        self.last_message_ts: Optional[str] = None
        self.last_message_text: Optional[str] = None

        # Track sent messages to avoid duplicates
        self.sent_messages: set = set()

    def _record_success(self) -> None:
        """Record successful Slack message send and reset circuit breaker"""
        if self.consecutive_failures > 0:
            logger.info("Slack messaging recovered, resetting circuit breaker")
        self.consecutive_failures = 0
        self.circuit_open = False

    def _record_failure(self, error: Exception, context: str) -> None:
        """
        Record failed Slack message send and open circuit breaker if threshold reached

        Args:
            error: The exception that occurred
            context: Context message for logging
        """
        self.consecutive_failures += 1
        logger.error(
            f"Failed to send {context} to Slack (failure #{self.consecutive_failures}): {error}"
        )

        if (
            self.consecutive_failures >= self.max_consecutive_failures
            and not self.circuit_open
        ):
            self.circuit_open = True
            logger.warning(
                f"⚠️ Circuit breaker OPENED: {self.consecutive_failures} consecutive Slack failures. "
                f"Disabling Slack notifications to prevent further errors. "
                f"RCA analysis will continue without progress updates."
            )

    async def _send_to_slack(
        self, text: str, context: str, use_hourglass: bool = False
    ) -> None:
        """
        Send message to Slack with circuit breaker protection
        Implements hourglass -> checkmark pattern for step updates

        Args:
            text: Message text to send
            context: Context for logging (e.g., "tool start message")
            use_hourglass: If True, adds hourglass emoji and updates previous message to checkmark
        """
        # Check circuit breaker
        if self.circuit_open:
            logger.debug(f"Circuit breaker open, skipping Slack message: {context}")
            return

        # Convert Markdown to Slack format
        text = markdown_to_slack(text)

        try:
            # Update previous message with checkmark if this is a new step
            if use_hourglass and self.last_message_ts and self.last_message_text:
                updated_text = self.last_message_text.replace(
                    ":hourglass_flowing_sand:", ":white_check_mark:"
                )
                await slack_event_service.update_message(
                    team_id=self.team_id,
                    channel=self.channel_id,
                    ts=self.last_message_ts,
                    text=updated_text,
                )

            # Send new message with hourglass if requested
            if use_hourglass:
                text = f":hourglass_flowing_sand: {text}"

            result = await slack_event_service.send_message(
                team_id=self.team_id,
                channel=self.channel_id,
                text=text,
                thread_ts=self.thread_ts,
            )

            # Track this message for future updates if it has hourglass
            if use_hourglass and result and result.get("ts"):
                self.last_message_ts = result["ts"]
                self.last_message_text = text

            self._record_success()
        except Exception as e:
            self._record_failure(e, context)

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool starts executing"""
        tool_name = serialized.get("name", "unknown_tool")

        # Redact tool input for logging
        redacted_input = redact_query_for_log(input_str) if input_str else "[EMPTY]"
        logger.info(f"Tool start - name: {tool_name}, input: {redacted_input}")

        # Get user-friendly message from enum mapping
        enum_message = TOOL_NAME_TO_MESSAGE.get(tool_name)
        base_message = (
            enum_message.value if enum_message else f"🔧 Using {tool_name}..."
        )

        # Extract contextual information from input
        context_info = self._extract_context_info(tool_name, input_str, kwargs)

        # Build final message with context
        message = f"{base_message} {context_info}" if context_info else base_message

        # Skip if this exact message was already sent (avoid duplicates)
        if message in self.sent_messages:
            logger.info(f"Skipping duplicate message: {message}")
            return

        # Track this message as sent
        self.sent_messages.add(message)

        await self._send_to_slack(
            text=message, context="tool start message", use_hourglass=True
        )

    def _extract_context_info(
        self, tool_name: str, input_str: str, kwargs: Dict[str, Any]
    ) -> str:
        """
        Extract service name, repo name, or file path from tool input

        Args:
            tool_name: Name of the tool being executed
            input_str: Input string (JSON or plain text)
            kwargs: Additional kwargs from callback

        Returns:
            Formatted context string (e.g., "`service-name`" or "`repo-name`")
        """
        try:
            # Try multiple parsing strategies
            input_data = {}

            # Strategy 0: Check if there's an 'inputs' dict in kwargs (LangChain standard)
            if "inputs" in kwargs and isinstance(kwargs["inputs"], dict):
                input_data = kwargs["inputs"]

            # Strategy 1: Check if there's a tool_input in kwargs
            elif "tool_input" in kwargs:
                tool_input = kwargs["tool_input"]
                if isinstance(tool_input, dict):
                    input_data = tool_input

            # Strategy 2: Try to parse input_str as JSON
            elif input_str:
                try:
                    input_data = json.loads(input_str)
                except (json.JSONDecodeError, TypeError, ValueError):
                    # Strategy 3: Try to parse as Python literal (handles single quotes)
                    try:
                        input_data = ast.literal_eval(input_str)
                    except (ValueError, SyntaxError):
                        # Strategy 4: Try to extract from dict-like string representation
                        # Match patterns like service_name='value' or service_name="value"
                        matches = re.findall(
                            r'(\w+)\s*[:=]\s*["\']([^"\']+)["\']', input_str
                        )
                        if matches:
                            input_data = dict(matches)
                        else:
                            # Strategy 5: Try to extract from key=value pairs
                            matches = re.findall(r"(\w+)\s*[:=]\s*(\S+)", input_str)
                            if matches:
                                input_data = {k: v.strip(",") for k, v in matches}

            # Extract service name for logs/metrics tools (don't log values to avoid PII)
            if tool_name in [
                "fetch_error_logs_tool",
                "fetch_logs_tool",
                "fetch_cpu_metrics_tool",
                "fetch_memory_metrics_tool",
                "fetch_http_latency_tool",
                "fetch_metrics_tool",
            ]:
                service_name = input_data.get("service_name")
                if service_name:
                    return f"for `{service_name}`"

            # Extract repo name for GitHub tools (don't log values to avoid PII)
            if tool_name in [
                "discover_service_name_tool",
                "scan_repository_for_services_tool",
                "read_repository_file_tool",
                "search_code_tool",
                "get_repository_commits_tool",
                "list_pull_requests_tool",
                "get_repository_tree_tool",
                "get_branch_recent_commits_tool",
                "get_repository_metadata_tool",
            ]:
                repo = input_data.get("repo") or input_data.get("name")
                file_path = input_data.get("file_path") or input_data.get("path")

                if repo and file_path:
                    return f"in `{repo}` → `{file_path}`"
                elif repo:
                    return f"in `{repo}`"
                elif file_path:
                    return f"`{file_path}`"

            return ""

        except Exception as e:
            logger.error(f"Failed to extract context info: {e}", exc_info=True)
            return ""

    async def on_tool_end(
        self,
        output: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool finishes executing"""
        # Only send tool output if explicitly enabled (can be verbose)
        if self.send_tool_output and output:
            # Truncate very long outputs
            truncated_output = output[: settings.RCA_SLACK_MESSAGE_MAX_LENGTH]
            if len(output) > settings.RCA_SLACK_MESSAGE_MAX_LENGTH:
                truncated_output += f"\n\n_(truncated, {len(output) - settings.RCA_SLACK_MESSAGE_MAX_LENGTH} more chars)_"

            await self._send_to_slack(
                text=f"```\n{truncated_output}\n```", context="tool output"
            )

    async def on_tool_error(
        self,
        error: Exception,
        **kwargs: Any,
    ) -> None:
        """Called when a tool encounters an error"""
        sanitized_error = sanitize_error_for_user(str(error))
        await self._send_to_slack(
            text=f"⚠️ Tool encountered an issue: {sanitized_error}", context="tool error"
        )

    async def on_agent_action(
        self,
        action: Any,
        **kwargs: Any,
    ) -> None:
        """Called when agent decides on an action"""
        # Extract agent's reasoning if available
        if hasattr(action, "log") and action.log:
            # Extract just the thought, not the full log
            log_text = action.log.strip()

            # Try to extract the "Thought:" part
            if "Thought:" in log_text:
                thought_start = log_text.index("Thought:") + len("Thought:")
                thought_text = log_text[thought_start:].split("\n")[0].strip()

                if thought_text and len(thought_text) > 10:  # Meaningful thought
                    await self._send_to_slack(
                        text=f"💭 _{thought_text}_", context="agent thought"
                    )

    async def on_agent_finish(
        self,
        finish: Any,
        **kwargs: Any,
    ) -> None:
        """Called when agent finishes"""
        # Update the last hourglass message to checkmark before finishing
        if self.last_message_ts and self.last_message_text:
            try:
                updated_text = self.last_message_text.replace(
                    ":hourglass_flowing_sand:", ":white_check_mark:"
                )
                await slack_event_service.update_message(
                    team_id=self.team_id,
                    channel=self.channel_id,
                    ts=self.last_message_ts,
                    text=updated_text,
                )
            except Exception as e:
                logger.error(f"Failed to update last message on finish: {e}")

        # Don't send "Analysis complete" message - the final output will be sent separately

    async def on_chain_error(
        self,
        error: Exception,
        **kwargs: Any,
    ) -> None:
        """Called when chain encounters an error"""
        sanitized_error = sanitize_error_for_user(str(error))
        await self._send_to_slack(
            text="❌ *Analysis encountered an error.*", context="chain error"
        )
        logger.debug(f"❌ Chain error details (not sent to user): {sanitized_error}")

    async def send_retry_notification(
        self, retry_count: int, max_retries: int, backoff_minutes: int
    ) -> None:
        """
        Send notification about job retry to user.

        Args:
            retry_count: Current retry attempt number
            max_retries: Maximum number of retries allowed
            backoff_minutes: Minutes until next retry
        """
        await self._send_to_slack(
            text=(
                f"⚠️ Job encountered an issue. Retrying in {backoff_minutes} minutes...\n"
                f"Attempt {retry_count}/{max_retries}"
            ),
            context="retry notification",
        )

    async def send_final_error(self, error_msg: str, retry_count: int) -> None:
        """
        Send final error message to user after max retries exceeded (sanitized).

        Args:
            error_msg: Raw error message (will be sanitized)
            retry_count: Number of retry attempts made (0 means 1 attempt, no retries)
        """
        user_friendly_msg = sanitize_error_for_user(error_msg)

        # Make message grammatically correct based on retry count
        # retry_count=0 means 1 attempt (no retries), retry_count=2 means 3 attempts total
        total_attempts = retry_count + 1
        if total_attempts == 1:
            attempt_text = "I couldn't complete the analysis."
        else:
            attempt_text = (
                f"I tried {total_attempts} times but couldn't complete the analysis."
            )

        await self._send_to_slack(
            text=(
                f"❌ {user_friendly_msg}. {attempt_text}\n\n"
                f"Please try rephrasing your query or contact support if the issue persists."
            ),
            context="final error message",
        )

    async def send_unexpected_error(self) -> None:
        """
        Send notification about unexpected error to user (sanitized, no details).
        """
        await self._send_to_slack(
            text=(
                "⚠️ An unexpected error occurred while processing your request.\n\n"
                "Our team has been notified. Please try again later or contact support if the issue persists."
            ),
            context="unexpected error message",
        )

    async def send_image_processing_notification(self, image_count: int) -> None:
        """
        Send notification that images are being processed by Gemini.

        Args:
            image_count: Number of images being analyzed
        """
        image_text = "the image" if image_count == 1 else "images"
        await self._send_to_slack(
            text=f"Analyzing {image_text} received.",
            context="image processing notification",
            use_hourglass=True,
        )

    async def send_no_healthy_integrations_message(
        self, unhealthy_providers: list[str] | None = None
    ) -> None:
        """
        Send notification when integrations are unhealthy.

        Args:
            unhealthy_providers: List of provider names that are unhealthy
        """
        if unhealthy_providers:
            for provider in unhealthy_providers:
                await self._send_to_slack(
                    text=(
                        f"⚠️ *{provider.capitalize()} integration is unavailable*\n\n"
                        f"The {provider.capitalize()} integration required for RCA analysis "
                        "is currently unhealthy or experiencing issues.\n\n"
                        "*To resolve this:*\n"
                        "• Check your integration health status in the dashboard\n"
                        "• Verify your API tokens and credentials are valid\n"
                        f"• Ensure {provider.capitalize()} service is accessible"
                    ),
                    context=f"unhealthy {provider} integration message",
                )
        else:
            await self._send_to_slack(
                text=(
                    "⚠️ *Unable to start RCA analysis*\n\n"
                    "No healthy integrations found for this workspace.\n\n"
                    "*To resolve this:*\n"
                    "• Check your integration health status in the dashboard\n"
                    "• Verify your API tokens and credentials are valid"
                ),
                context="no healthy integrations message",
            )

    async def send_missing_integration_message(self, provider: str) -> None:
        """
        Send notification when a required integration is not configured.

        Args:
            provider: The provider name that is missing (e.g., 'github')
        """
        await self._send_to_slack(
            text=(
                f"⚠️ *{provider.capitalize()} integration is not configured*\n\n"
                f"The {provider.capitalize()} integration is required for RCA analysis "
                "but has not been set up for this workspace.\n\n"
                "*To resolve this:*\n"
                f"• Connect your {provider.capitalize()} account in the dashboard\n"
                "• Ensure the integration is properly configured"
            ),
            context=f"missing {provider} integration message",
        )

    async def send_onboarding_required_message(self) -> None:
        """
        Send notification when workspace owner has not completed onboarding.
        """
        integrations_url = f"{settings.WEB_APP_URL}/integrations" if settings.WEB_APP_URL else "the dashboard"
        await self._send_to_slack(
            text=(
                "⚠️ *Onboarding not completed*\n\n"
                "Please complete the onboarding process to use RCA analysis.\n\n"
                "*To resolve this:*\n"
                f"• <{integrations_url}|Click here> to complete you onboarding and connect your GitHub account"
            ),
            context="onboarding required message",
        )

    async def send_degraded_integrations_warning(
        self, unhealthy_providers: list[str]
    ) -> None:
        """
        Send warning when some integrations are unhealthy but RCA will proceed.

        Args:
            unhealthy_providers: List of provider names that are unhealthy
        """
        providers_list = ", ".join([p.capitalize() for p in unhealthy_providers])
        await self._send_to_slack(
            text=(
                f"⚠️ *Some integrations are unhealthy/degraded:* {providers_list}\n\n"
                "Proceeding with available tools. Some capabilities may be limited."
            ),
            context="degraded integrations warning",
        )


class ToolMetricsCallback(AsyncCallbackHandler):
    """Callback handler for recording tool execution metrics"""

    def __init__(self):
        super().__init__()
        self.tool_start_times: Dict[str, float] = {}

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Record tool start time"""
        tool_name = serialized.get("name", "unknown")
        run_id = kwargs.get("run_id", str(uuid.uuid4()))
        self.tool_start_times[str(run_id)] = time.time()

        logger.debug(f"Tool started: {tool_name}")

    async def on_tool_end(
        self,
        output: Any,
        **kwargs: Any,
    ) -> None:
        """Record successful tool execution metrics"""

        run_id = str(kwargs.get("run_id", ""))
        tool_name = kwargs.get("name", "unknown")

        # Record tool execution count
        TOOL_METRICS["rca_tool_executions_total"].add(
            1,
            {
                "status": "success",
            },
        )

        # Record tool execution duration
        if run_id in self.tool_start_times:
            duration = time.time() - self.tool_start_times[run_id]
            TOOL_METRICS["rca_tool_execution_duration_seconds"].record(
                duration,
                {
                    "tool_name": tool_name,
                },
            )
            del self.tool_start_times[run_id]

    async def on_tool_error(
        self,
        error: Exception,
        **kwargs: Any,
    ) -> None:
        """Record tool execution error metrics"""

        run_id = str(kwargs.get("run_id", ""))
        tool_name = kwargs.get("name", "unknown")
        error_type = type(error).__name__

        TOOL_METRICS["rca_tool_executions_total"].add(
            1,
            {
                "status": "failure",
            },
        )

        TOOL_METRICS["rca_tool_execution_errors_total"].add(
            1,
            {
                "tool_name": tool_name,
                "error_type": error_type,
            },
        )

        # Clean up start time
        if run_id in self.tool_start_times:
            del self.tool_start_times[run_id]
