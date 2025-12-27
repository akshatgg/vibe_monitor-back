"""
Chat module for web-based RCA conversations.

Provides:
- Chat sessions and turns management
- SSE streaming for real-time updates
- Feedback collection at turn level
"""

from app.chat.router import router

__all__ = ["router"]
