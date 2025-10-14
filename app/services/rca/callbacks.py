"""
Custom LangChain callbacks for streaming RCA agent progress to Slack
"""
import logging
from typing import Any, Dict, Optional
from langchain.callbacks.base import AsyncCallbackHandler
from app.slack.service import slack_event_service

logger = logging.getLogger(__name__)


class SlackProgressCallback(AsyncCallbackHandler):
    """
    Callback handler that sends agent thinking process to Slack in real-time
    """

    def __init__(
        self,
        team_id: str,
        channel_id: str,
        thread_ts: Optional[str] = None,
        send_tool_output: bool = True,
    ):
        """
        Initialize Slack progress callback

        Args:
            team_id: Slack team ID
            channel_id: Channel to send updates to
            thread_ts: Thread timestamp (for threaded replies)
            send_tool_output: Whether to send full tool outputs (can be verbose)
        """
        self.team_id = team_id
        self.channel_id = channel_id
        self.thread_ts = thread_ts
        self.send_tool_output = send_tool_output
        self.step_counter = 0

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool starts executing"""
        self.step_counter += 1
        tool_name = serialized.get("name", "unknown_tool")

        # Map tool names to user-friendly messages
        friendly_messages = {
            "fetch_error_logs_tool": "🔍 Checking error logs...",
            "fetch_logs_tool": "📜 Fetching logs...",
            "fetch_cpu_metrics_tool": "📊 Analyzing CPU metrics...",
            "fetch_memory_metrics_tool": "💾 Analyzing memory usage...",
            "fetch_http_latency_tool": "⏱️ Checking HTTP latency...",
            "fetch_metrics_tool": "📈 Fetching metrics...",
            "list_repositories_tool": "📦 Listing GitHub repositories...",
            "list_all_services_tool": "🔎 Discovering all services in workspace...",
            "discover_service_name_tool": "🏷️ Identifying service name from repository...",
            "scan_repository_for_services_tool": "🔍 Scanning repository for service names...",
            "read_repository_file_tool": "📄 Reading code file...",
            "search_code_tool": "🔎 Searching codebase...",
            "get_repository_commits_tool": "📝 Checking recent commits...",
            "list_pull_requests_tool": "🔀 Reviewing pull requests...",
            "download_file_tool": "⬇️ Downloading file...",
            "get_repository_tree_tool": "🌳 Exploring repository structure...",
            "get_branch_recent_commits_tool": "🌿 Checking branch commits...",
            "get_repository_metadata_tool": "ℹ️ Fetching repository metadata...",
        }

        message = friendly_messages.get(tool_name, f"🔧 Using {tool_name}...")

        try:
            await slack_event_service.send_message(
                team_id=self.team_id,
                channel=self.channel_id,
                text=f"*Step {self.step_counter}:* {message}",
                thread_ts=self.thread_ts,
            )
        except Exception as e:
            logger.error(f"Failed to send tool start message to Slack: {e}")

    async def on_tool_end(
        self,
        output: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool finishes executing"""
        # Only send tool output if explicitly enabled (can be verbose)
        if self.send_tool_output and output:
            try:
                # Truncate very long outputs
                max_length = 500
                truncated_output = output[:max_length]
                if len(output) > max_length:
                    truncated_output += f"\n\n_(truncated, {len(output) - max_length} more chars)_"

                await slack_event_service.send_message(
                    team_id=self.team_id,
                    channel=self.channel_id,
                    text=f"```\n{truncated_output}\n```",
                    thread_ts=self.thread_ts,
                )
            except Exception as e:
                logger.error(f"Failed to send tool output to Slack: {e}")

    async def on_tool_error(
        self,
        error: Exception,
        **kwargs: Any,
    ) -> None:
        """Called when a tool encounters an error"""
        try:
            await slack_event_service.send_message(
                team_id=self.team_id,
                channel=self.channel_id,
                text=f"⚠️ Tool encountered an issue: {str(error)[:200]}",
                thread_ts=self.thread_ts,
            )
        except Exception as e:
            logger.error(f"Failed to send tool error to Slack: {e}")

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
                    try:
                        await slack_event_service.send_message(
                            team_id=self.team_id,
                            channel=self.channel_id,
                            text=f"💭 _{thought_text}_",
                            thread_ts=self.thread_ts,
                        )
                    except Exception as e:
                        logger.error(f"Failed to send agent thought to Slack: {e}")

    async def on_agent_finish(
        self,
        finish: Any,
        **kwargs: Any,
    ) -> None:
        """Called when agent finishes"""
        try:
            await slack_event_service.send_message(
                team_id=self.team_id,
                channel=self.channel_id,
                text="✅ *Analysis complete!*",
                thread_ts=self.thread_ts,
            )
        except Exception as e:
            logger.error(f"Failed to send agent finish message to Slack: {e}")

    async def on_chain_error(
        self,
        error: Exception,
        **kwargs: Any,
    ) -> None:
        """Called when chain encounters an error"""
        try:
            await slack_event_service.send_message(
                team_id=self.team_id,
                channel=self.channel_id,
                text=f"❌ *Analysis encountered an error:* {str(error)[:300]}",
                thread_ts=self.thread_ts,
            )
        except Exception as e:
            logger.error(f"Failed to send chain error to Slack: {e}")
