"""
Base notifier interface for RCA updates.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseNotifier(ABC):
    """
    Abstract base class for sending RCA processing updates.

    Implementations should handle channel-specific logic
    (Slack API, Redis pub/sub, etc.)
    """

    @abstractmethod
    async def on_status(self, message: str) -> None:
        """
        Send a status update.

        Args:
            message: Status message to display
        """
        pass

    @abstractmethod
    async def on_tool_start(
        self, tool_name: str, step_id: Optional[str] = None
    ) -> None:
        """
        Notify that a tool execution has started.

        Args:
            tool_name: Name of the tool being executed
            step_id: Optional step ID for tracking
        """
        pass

    @abstractmethod
    async def on_tool_end(
        self,
        tool_name: str,
        status: str,
        content: Optional[str] = None,
    ) -> None:
        """
        Notify that a tool execution has completed.

        Args:
            tool_name: Name of the tool
            status: Completion status (completed/failed)
            content: Optional result content
        """
        pass

    @abstractmethod
    async def on_complete(self, final_response: str) -> None:
        """
        Notify that processing is complete with final response.

        Args:
            final_response: The final RCA response
        """
        pass

    @abstractmethod
    async def on_error(self, message: str, action_url: Optional[str] = None) -> None:
        """
        Notify that an error occurred.

        Args:
            message: Error message
            action_url: Optional URL for user to take action (e.g., set up integrations)
        """
        pass

    async def on_thinking(self, content: str) -> None:
        """
        Notify about agent thinking/reasoning.

        Optional - default implementation does nothing.
        Override in subclasses if needed.

        Args:
            content: Thinking content
        """
        pass
