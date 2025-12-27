"""
Notifiers for sending RCA updates to different channels.

Provides a unified interface for:
- Web (Redis pub/sub → SSE)
- Slack (Slack API → Thread updates)
- MS Teams (future)
"""

from app.chat.notifiers.base import BaseNotifier
from app.chat.notifiers.web import WebNotifier
from app.chat.notifiers.web_callback import WebProgressCallback

__all__ = ["BaseNotifier", "WebNotifier", "WebProgressCallback"]
