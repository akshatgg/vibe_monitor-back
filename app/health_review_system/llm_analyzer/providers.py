"""
LLM Provider implementations for Health Review analysis.

Supports multiple LLM backends via a provider pattern.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def get_llm(self) -> BaseChatModel:
        """Get the LangChain LLM instance."""
        pass

    @abstractmethod
    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: Optional[List[Any]] = None,
        callbacks: Optional[List[Any]] = None,
    ) -> str:
        """
        Invoke the LLM with prompts.

        Args:
            system_prompt: System instructions
            user_prompt: User query/context
            tools: Optional list of tools for tool calling
            callbacks: Optional LangChain callbacks (e.g. Langfuse)

        Returns:
            LLM response as string
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass


class GroqProvider(BaseLLMProvider):
    """Groq LLM provider using Llama models."""

    def __init__(self, model: Optional[str] = None):
        self.model = model or settings.GROQ_LLM_MODEL
        if not self.model:
            raise ValueError("GROQ_LLM_MODEL not configured. Please set it in environment variables.")
        self._llm: Optional[ChatGroq] = None

    def get_llm(self) -> ChatGroq:
        """Get or create the Groq LLM instance."""
        if self._llm is None:
            if not settings.GROQ_API_KEY:
                raise ValueError(
                    "GROQ_API_KEY not configured. Please set it in environment variables."
                )
            self._llm = ChatGroq(
                model=self.model,
                temperature=settings.HEALTH_REVIEW_LLM_TEMPERATURE,
            )
            logger.info(f"GroqProvider initialized with model: {self.model}")
        return self._llm

    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: Optional[List[Any]] = None,
        callbacks: Optional[List[Any]] = None,
    ) -> str:
        """Invoke Groq LLM."""
        llm = self.get_llm()

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        config = {"callbacks": callbacks} if callbacks else {}

        if tools:
            llm_with_tools = llm.bind_tools(tools)
            response = await llm_with_tools.ainvoke(messages, config=config)
        else:
            response = await llm.ainvoke(messages, config=config)

        return response.content

    @property
    def name(self) -> str:
        return "groq"


class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM provider."""

    def __init__(self, model: Optional[str] = None):
        self.model = model or settings.GEMINI_LLM_MODEL
        if not self.model:
            raise ValueError("GEMINI_LLM_MODEL not configured. Please set it in environment variables.")
        self._llm: Optional[ChatGoogleGenerativeAI] = None

    def get_llm(self) -> ChatGoogleGenerativeAI:
        """Get or create the Gemini LLM instance."""
        if self._llm is None:
            if not settings.GEMINI_API_KEY:
                raise ValueError(
                    "GEMINI_API_KEY not configured. Please set it in environment variables."
                )
            self._llm = ChatGoogleGenerativeAI(
                model=self.model,
                google_api_key=settings.GEMINI_API_KEY,
                temperature=settings.HEALTH_REVIEW_LLM_TEMPERATURE,
            )
            logger.info(f"GeminiProvider initialized with model: {self.model}")
        return self._llm

    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: Optional[List[Any]] = None,
        callbacks: Optional[List[Any]] = None,
    ) -> str:
        """Invoke Gemini LLM."""
        llm = self.get_llm()

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        config = {"callbacks": callbacks} if callbacks else {}

        if tools:
            llm_with_tools = llm.bind_tools(tools)
            response = await llm_with_tools.ainvoke(messages, config=config)
        else:
            response = await llm.ainvoke(messages, config=config)

        return response.content

    @property
    def name(self) -> str:
        return "gemini"


def get_default_provider() -> BaseLLMProvider:
    """
    Get the default LLM provider based on available configuration.

    Priority:
    1. Groq (if GROQ_API_KEY is set)
    2. Gemini (if GEMINI_API_KEY is set)

    Raises:
        ValueError: If no LLM provider is configured
    """
    if settings.GROQ_API_KEY:
        logger.info("Using Groq as default LLM provider")
        return GroqProvider()

    if settings.GEMINI_API_KEY:
        logger.info("Using Gemini as default LLM provider")
        return GeminiProvider()

    raise ValueError(
        "No LLM provider configured. Please set GROQ_API_KEY or GEMINI_API_KEY."
    )
