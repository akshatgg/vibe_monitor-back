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

from .providers import get_llm_for_workspace, DEFAULT_MODELS
from .service import LLMConfigService
from .router import router as llm_router

__all__ = [
    "get_llm_for_workspace",
    "DEFAULT_MODELS",
    "LLMConfigService",
    "llm_router",
]
