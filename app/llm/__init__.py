"""
BYOLLM (Bring Your Own LLM) Module

Allows workspace owners to configure their own LLM provider (OpenAI, Azure OpenAI,
Google Gemini) instead of using VibeMonitor's default AI (Groq).

Features:
- Per-workspace LLM configuration
- Encrypted API key storage
- Provider verification
- Rate limit bypass for BYOLLM users
"""

from .providers import get_llm_for_workspace
from .router import router as llm_router
from .service import LLMConfigService

__all__ = [
    "get_llm_for_workspace",
    "LLMConfigService",
    "llm_router",
]
