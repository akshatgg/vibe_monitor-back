"""
LLM Provider Factory for BYOLLM (Bring Your Own LLM).

This module provides a factory function to get the appropriate LLM instance
for a workspace based on its configuration.

Supported providers:
- vibemonitor: Default provider using Groq (no configuration needed)
- openai: OpenAI API (requires api_key)
- azure_openai: Azure OpenAI (requires api_key, endpoint, deployment_name)
- gemini: Google Gemini (requires api_key)
"""

import json
import logging
from typing import Optional

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import LLMProviderConfig, LLMProvider
from app.utils.token_processor import token_processor


logger = logging.getLogger(__name__)


# Default models per provider
DEFAULT_MODELS = {
    "vibemonitor": settings.GROQ_LLM_MODEL or "llama-3.3-70b-versatile",
    "openai": "gpt-4-turbo",
    "azure_openai": None,  # Must be specified via deployment_name
    "gemini": "gemini-1.5-pro",
}


async def get_llm_for_workspace(
    workspace_id: str,
    db: AsyncSession,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> BaseChatModel:
    """
    Get the appropriate LLM instance for a workspace.

    Falls back to VibeMonitor default (Groq) if no custom config exists.

    Args:
        workspace_id: The workspace ID to get LLM for
        db: Database session for querying LLM config
        temperature: Override temperature (defaults to RCA_AGENT_TEMPERATURE)
        max_tokens: Override max tokens (defaults to RCA_AGENT_MAX_TOKENS)

    Returns:
        BaseChatModel: LangChain chat model instance

    Raises:
        ValueError: If required configuration is missing for the provider
    """
    # Use defaults from settings if not specified
    if temperature is None:
        temperature = settings.RCA_AGENT_TEMPERATURE
    if max_tokens is None:
        max_tokens = settings.RCA_AGENT_MAX_TOKENS

    # Query workspace LLM config
    result = await db.execute(
        select(LLMProviderConfig).where(LLMProviderConfig.workspace_id == workspace_id)
    )
    config = result.scalar_one_or_none()

    # Default: VibeMonitor AI (Groq)
    if config is None or config.provider == LLMProvider.VIBEMONITOR:
        logger.info(
            f"Using VibeMonitor default LLM (Groq) for workspace {workspace_id}"
        )
        return _create_groq_llm(temperature, max_tokens)

    # Custom provider configured
    logger.info(
        f"Using custom LLM provider '{config.provider.value}' for workspace {workspace_id}"
    )

    try:
        # Decrypt config
        decrypted_config = {}
        if config.config_encrypted:
            decrypted_config = json.loads(
                token_processor.decrypt(config.config_encrypted)
            )

        model_name = config.model_name or DEFAULT_MODELS.get(config.provider.value)

        if config.provider == LLMProvider.OPENAI:
            return _create_openai_llm(
                decrypted_config, model_name, temperature, max_tokens
            )

        elif config.provider == LLMProvider.AZURE_OPENAI:
            return _create_azure_openai_llm(
                decrypted_config, model_name, temperature, max_tokens
            )

        elif config.provider == LLMProvider.GEMINI:
            return _create_gemini_llm(
                decrypted_config, model_name, temperature, max_tokens
            )

        else:
            # Unknown provider, fall back to Groq
            logger.warning(
                f"Unknown provider '{config.provider}' for workspace {workspace_id}, "
                f"falling back to VibeMonitor default"
            )
            return _create_groq_llm(temperature, max_tokens)

    except Exception as e:
        logger.error(
            f"Error creating LLM for workspace {workspace_id}: {e}. "
            f"Falling back to VibeMonitor default."
        )
        return _create_groq_llm(temperature, max_tokens)


def _create_groq_llm(temperature: float, max_tokens: int) -> ChatGroq:
    """Create VibeMonitor default LLM (Groq)."""
    if not settings.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not configured in environment")

    return ChatGroq(
        api_key=settings.GROQ_API_KEY,
        model=settings.GROQ_LLM_MODEL or DEFAULT_MODELS["vibemonitor"],
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _create_openai_llm(
    config: dict,
    model_name: str,
    temperature: float,
    max_tokens: int,
) -> ChatOpenAI:
    """Create OpenAI LLM."""
    api_key = config.get("api_key")
    if not api_key:
        raise ValueError("OpenAI API key not configured")

    return ChatOpenAI(
        api_key=api_key,
        model=model_name or DEFAULT_MODELS["openai"],
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _create_azure_openai_llm(
    config: dict,
    model_name: str,
    temperature: float,
    max_tokens: int,
) -> AzureChatOpenAI:
    """Create Azure OpenAI LLM."""
    api_key = config.get("api_key")
    endpoint = config.get("endpoint")
    deployment_name = config.get("deployment_name") or model_name
    api_version = config.get("api_version", "2024-02-01")

    if not api_key:
        raise ValueError("Azure OpenAI API key not configured")
    if not endpoint:
        raise ValueError("Azure OpenAI endpoint not configured")
    if not deployment_name:
        raise ValueError("Azure OpenAI deployment name not configured")

    return AzureChatOpenAI(
        api_key=api_key,
        azure_endpoint=endpoint,
        azure_deployment=deployment_name,
        api_version=api_version,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _create_gemini_llm(
    config: dict,
    model_name: str,
    temperature: float,
    max_tokens: int,
) -> ChatGoogleGenerativeAI:
    """Create Google Gemini LLM."""
    api_key = config.get("api_key")
    if not api_key:
        raise ValueError("Gemini API key not configured")

    return ChatGoogleGenerativeAI(
        google_api_key=api_key,
        model=model_name or DEFAULT_MODELS["gemini"],
        temperature=temperature,
        max_output_tokens=max_tokens,
    )


async def is_byollm_workspace(workspace_id: str, db: AsyncSession) -> bool:
    """
    Check if workspace has configured their own LLM (not using VibeMonitor AI).

    This is used for rate limit bypass - BYOLLM users are not rate limited.

    Args:
        workspace_id: The workspace ID to check
        db: Database session

    Returns:
        bool: True if workspace uses custom LLM, False if using VibeMonitor default
    """
    result = await db.execute(
        select(LLMProviderConfig.provider).where(
            LLMProviderConfig.workspace_id == workspace_id
        )
    )
    provider = result.scalar_one_or_none()

    # If no config exists or provider is vibemonitor, not BYOLLM
    if provider is None:
        return False

    return provider != LLMProvider.VIBEMONITOR
