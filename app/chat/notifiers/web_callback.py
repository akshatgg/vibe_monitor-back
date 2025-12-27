"""
LangChain callback handler for web chat SSE streaming.

Wraps the WebNotifier to provide LangChain-compatible callbacks
for the RCA agent.
"""

import logging
from typing import Any, Dict

from langchain.callbacks.base import AsyncCallbackHandler
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.notifiers.web import WebNotifier
from app.services.rca.get_service_name.enums import TOOL_NAME_TO_MESSAGE

logger = logging.getLogger(__name__)


class WebProgressCallback(AsyncCallbackHandler):
    """
    LangChain callback handler that streams RCA progress to web clients via SSE.

    Uses WebNotifier internally to publish events to Redis pub/sub.
    """

    def __init__(
        self,
        turn_id: str,
        db: AsyncSession,
    ):
        """
        Initialize web progress callback.

        Args:
            turn_id: Chat turn ID for routing events
            db: Database session for persisting steps
        """
        self.turn_id = turn_id
        self.db = db
        self.notifier = WebNotifier(turn_id=turn_id, db=db)
        self.step_counter = 0
        # Track current step for matching tool_start with tool_end
        self._current_step_id: str | None = None
        self._current_tool_display_name: str | None = None

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool starts executing."""
        tool_name = serialized.get("name", "unknown_tool")

        # Get user-friendly message from enum mapping (same as Slack callback)
        enum_message = TOOL_NAME_TO_MESSAGE.get(tool_name)
        display_name = enum_message.value if enum_message else f"Using {tool_name}..."

        # Call notifier and capture the database step_id for matching with tool_end
        step_id = await self.notifier.on_tool_start(tool_name=display_name)

        # Store current step info for matching with tool_end
        self._current_step_id = step_id
        self._current_tool_display_name = display_name

        logger.debug(
            f"[Turn {self.turn_id}] Tool started: {tool_name} (step_id: {step_id})"
        )

    async def on_tool_end(
        self,
        output: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool finishes executing."""
        # Use tracked step_id and display_name from on_tool_start for consistent matching
        step_id = self._current_step_id
        display_name = self._current_tool_display_name

        # Truncate long outputs
        truncated_output = output[:500] if output else None

        await self.notifier.on_tool_end(
            tool_name=display_name or "Tool",
            status="completed",
            content=truncated_output,
            step_id=step_id,
        )

        # Clear current step tracking
        self._current_step_id = None
        self._current_tool_display_name = None

    async def on_tool_error(
        self,
        error: Exception,
        **kwargs: Any,
    ) -> None:
        """Called when a tool encounters an error."""
        # Use tracked step_id and display_name from on_tool_start for consistent matching
        step_id = self._current_step_id
        display_name = self._current_tool_display_name

        await self.notifier.on_tool_end(
            tool_name=display_name or "Tool",
            status="failed",
            content=str(error)[:200],
            step_id=step_id,
        )

        # Clear current step tracking
        self._current_step_id = None
        self._current_tool_display_name = None

    async def on_agent_action(
        self,
        action: Any,
        **kwargs: Any,
    ) -> None:
        """Called when agent decides on an action."""
        # Extract agent's reasoning if available
        if hasattr(action, "log") and action.log:
            log_text = action.log.strip()

            # Try to extract the "Thought:" part
            if "Thought:" in log_text:
                thought_start = log_text.index("Thought:") + len("Thought:")
                thought_text = log_text[thought_start:].split("\n")[0].strip()

                if thought_text and len(thought_text) > 10:
                    await self.notifier.on_thinking(thought_text)

    async def on_agent_finish(
        self,
        finish: Any,
        **kwargs: Any,
    ) -> None:
        """Called when agent finishes."""
        # The final response will be sent by the worker via on_complete
        pass

    async def on_chain_error(
        self,
        error: Exception,
        **kwargs: Any,
    ) -> None:
        """Called when chain encounters an error."""
        await self.notifier.on_error(str(error)[:500])

    async def send_status(self, message: str) -> None:
        """Send a status update (not part of LangChain interface, used directly)."""
        await self.notifier.on_status(message)

    async def send_complete(self, final_response: str) -> None:
        """Mark processing as complete with final response."""
        await self.notifier.on_complete(final_response)

    async def send_error(self, message: str) -> None:
        """Send an error notification."""
        await self.notifier.on_error(message)
