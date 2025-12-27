"""
Web notifier for SSE streaming via Redis pub/sub.
"""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.notifiers.base import BaseNotifier
from app.chat.service import ChatService
from app.core.config import settings
from app.core.redis import publish_event
from app.models import TurnStatus, StepType, StepStatus

logger = logging.getLogger(__name__)


class WebNotifier(BaseNotifier):
    """
    Notifier for web chat via SSE.

    Publishes events to Redis and persists steps to database.
    SSE endpoint subscribes to Redis channel to stream to client.
    """

    def __init__(
        self,
        turn_id: str,
        db: AsyncSession,
    ):
        """
        Initialize web notifier.

        Args:
            turn_id: Chat turn ID
            db: Database session for persisting steps
        """
        self.turn_id = turn_id
        self.db = db
        self.channel = f"turn:{turn_id}"
        self.service = ChatService(db)

    async def on_status(self, message: str) -> None:
        """Send a status update."""
        # Save to database
        await self.service.add_turn_step(
            turn_id=self.turn_id,
            step_type=StepType.STATUS,
            content=message,
            status=StepStatus.COMPLETED,
        )
        await self.db.commit()

        # Publish to Redis
        await publish_event(
            self.channel,
            {
                "event": "status",
                "content": message,
            },
        )
        logger.debug(f"[Turn {self.turn_id}] Status: {message}")

    async def on_tool_start(self, tool_name: str) -> str:
        """
        Notify that a tool execution has started.

        Returns:
            step_id: The database step ID for matching with tool_end
        """
        # Save to database
        step = await self.service.add_turn_step(
            turn_id=self.turn_id,
            step_type=StepType.TOOL_CALL,
            tool_name=tool_name,
            status=StepStatus.RUNNING,
        )
        await self.db.commit()

        # Publish to Redis
        await publish_event(
            self.channel,
            {
                "event": "tool_start",
                "tool_name": tool_name,
                "step_id": step.id,
            },
        )
        logger.debug(f"[Turn {self.turn_id}] Tool started: {tool_name}")

        # Return step_id for matching with tool_end
        return step.id

    async def on_tool_end(
        self,
        tool_name: str,
        status: str,
        content: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> None:
        """Notify that a tool execution has completed."""
        # Update database step if step_id provided (persists completion status and content)
        if step_id:
            await self.service.update_step_status(
                step_id=step_id,
                status=StepStatus.COMPLETED
                if status == "completed"
                else StepStatus.FAILED,
                content=content[: settings.RCA_WEB_TOOL_OUTPUT_MAX_LENGTH]
                if content
                else None,
            )
            await self.db.commit()

        # Publish to Redis with step_id for frontend matching
        await publish_event(
            self.channel,
            {
                "event": "tool_end",
                "tool_name": tool_name,
                "status": status,
                "content": content[: settings.RCA_WEB_TOOL_OUTPUT_MAX_LENGTH]
                if content
                else None,
                "step_id": step_id,  # For matching with tool_start
            },
        )
        logger.debug(f"[Turn {self.turn_id}] Tool ended: {tool_name} ({status})")

    async def on_complete(self, final_response: str) -> None:
        """Notify that processing is complete with final response."""
        # Update turn in database
        await self.service.update_turn_status(
            turn_id=self.turn_id,
            status=TurnStatus.COMPLETED,
            final_response=final_response,
        )
        await self.db.commit()

        # Publish to Redis
        await publish_event(
            self.channel,
            {
                "event": "complete",
                "final_response": final_response,
            },
        )
        logger.info(f"[Turn {self.turn_id}] Processing complete")

    async def on_error(self, message: str) -> None:
        """Notify that an error occurred."""
        # Update turn status to failed
        await self.service.update_turn_status(
            turn_id=self.turn_id,
            status=TurnStatus.FAILED,
        )
        await self.db.commit()

        # Publish to Redis
        await publish_event(
            self.channel,
            {
                "event": "error",
                "message": message,
            },
        )
        # Structured logging for log aggregation tools (Datadog, CloudWatch)
        logger.error(
            f"[Turn {self.turn_id}] Error: {message}",
            extra={"turn_id": self.turn_id, "error_message": message},
        )

    async def on_thinking(self, content: str) -> None:
        """Notify about agent thinking/reasoning."""
        # Save to database (with truncation for storage)
        await self.service.add_turn_step(
            turn_id=self.turn_id,
            step_type=StepType.THINKING,
            content=content[: settings.RCA_WEB_THINKING_MAX_LENGTH],
            status=StepStatus.COMPLETED,
        )
        await self.db.commit()

        # Publish to Redis (optional - frontend might not display this)
        await publish_event(
            self.channel,
            {
                "event": "thinking",
                "content": content[: settings.RCA_WEB_THINKING_SSE_MAX_LENGTH],
            },
        )
