"""
Custom LangChain callbacks for streaming RCA agent progress to Slack
"""
import json
import re
import logging
from typing import Any, Dict, Optional
from langchain.callbacks.base import AsyncCallbackHandler
from app.slack.service import slack_event_service
from app.services.rca.get_service_name.enums import TOOL_NAME_TO_MESSAGE

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

        # Log for debugging
        logger.info(f"Tool start - name: {tool_name}, input_str: {input_str[:200] if input_str else 'None'}, kwargs keys: {list(kwargs.keys())}")

        # Get user-friendly message from enum mapping
        enum_message = TOOL_NAME_TO_MESSAGE.get(tool_name)
        base_message = enum_message.value if enum_message else f"🔧 Using {tool_name}..."

        # Extract contextual information from input
        context_info = self._extract_context_info(tool_name, input_str, kwargs)

        # Build final message with context
        message = f"{base_message} {context_info}" if context_info else base_message

        try:
            await slack_event_service.send_message(
                team_id=self.team_id,
                channel=self.channel_id,
                text=f"*Step {self.step_counter}:* {message}",
                thread_ts=self.thread_ts,
            )
        except Exception as e:
            logger.error(f"Failed to send tool start message to Slack: {e}")

    def _extract_context_info(self, tool_name: str, input_str: str, kwargs: Dict[str, Any]) -> str:
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
            # Log the input for debugging
            logger.info(f"Extracting context for {tool_name} with input: {input_str[:200] if input_str else 'None'}")
            if kwargs:
                logger.info(f"kwargs: {kwargs}")

            # Try multiple parsing strategies
            input_data = {}

            # Strategy 0: Check if there's an 'inputs' dict in kwargs (LangChain standard)
            if "inputs" in kwargs and isinstance(kwargs["inputs"], dict):
                input_data = kwargs["inputs"]
                logger.info(f"Using inputs from kwargs: {input_data}")

            # Strategy 1: Check if there's a tool_input in kwargs
            elif "tool_input" in kwargs:
                tool_input = kwargs["tool_input"]
                if isinstance(tool_input, dict):
                    input_data = tool_input
                    logger.info(f"Using tool_input from kwargs: {input_data}")

            # Strategy 2: Try to parse input_str as JSON
            elif input_str:
                try:
                    input_data = json.loads(input_str)
                    logger.info(f"Successfully parsed JSON: {input_data}")
                except (json.JSONDecodeError, TypeError, ValueError):
                    # Strategy 3: Try to parse as Python literal (handles single quotes)
                    try:
                        import ast
                        input_data = ast.literal_eval(input_str)
                        logger.info(f"Successfully parsed Python literal: {input_data}")
                    except (ValueError, SyntaxError):
                        # Strategy 4: Try to extract from dict-like string representation
                        # Match patterns like service_name='value' or service_name="value"
                        matches = re.findall(r'(\w+)\s*[:=]\s*["\']([^"\']+)["\']', input_str)
                        if matches:
                            input_data = dict(matches)
                            logger.info(f"Extracted from regex: {input_data}")
                        else:
                            # Strategy 5: Try to extract from key=value pairs
                            matches = re.findall(r'(\w+)\s*[:=]\s*(\S+)', input_str)
                            if matches:
                                input_data = {k: v.strip(',') for k, v in matches}
                                logger.info(f"Extracted from key=value pairs: {input_data}")

            # Extract service name for logs/metrics tools
            if tool_name in [
                "fetch_error_logs_tool",
                "fetch_logs_tool",
                "fetch_cpu_metrics_tool",
                "fetch_memory_metrics_tool",
                "fetch_http_latency_tool",
                "fetch_metrics_tool"
            ]:
                service_name = input_data.get("service_name")
                if service_name:
                    logger.info(f"Found service_name: {service_name}")
                    return f"for `{service_name}`"
                else:
                    logger.warning(f"No service_name found in input_data: {input_data}")

            # Extract repo name for GitHub tools
            if tool_name in [
                "discover_service_name_tool",
                "scan_repository_for_services_tool",
                "read_repository_file_tool",
                "search_code_tool",
                "get_repository_commits_tool",
                "list_pull_requests_tool",
                "download_file_tool",
                "get_repository_tree_tool",
                "get_branch_recent_commits_tool",
                "get_repository_metadata_tool"
            ]:
                repo = input_data.get("repo") or input_data.get("name")
                file_path = input_data.get("file_path") or input_data.get("path")

                if repo and file_path:
                    logger.info(f"Found repo: {repo}, file_path: {file_path}")
                    return f"in `{repo}` → `{file_path}`"
                elif repo:
                    logger.info(f"Found repo: {repo}")
                    return f"in `{repo}`"
                elif file_path:
                    logger.info(f"Found file_path: {file_path}")
                    return f"`{file_path}`"
                else:
                    logger.warning(f"No repo/file_path found in input_data: {input_data}")

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
