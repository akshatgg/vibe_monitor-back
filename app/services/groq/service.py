import asyncio
import logging
from typing import List
from .client import GroqClient
from .models import ChatRequest, ChatResponse, ChatMessage, ChatRole

logger = logging.getLogger(__name__)


class GroqService:
    def __init__(self):
        self.client = GroqClient()
        logger.info("GroqService initialized")

    async def chat_completion(self, request: ChatRequest) -> ChatResponse:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.client.chat_completion, request)

    async def simple_chat(
        self,
        message: str,
        model: str = "openai/gpt-oss-20b",
        temperature: float = 0.7,
        max_tokens: int = 150
    ) -> str:
        request = ChatRequest(
            model=model,
            messages=[ChatMessage(role=ChatRole.USER, content=message)],
            temperature=temperature,
            max_tokens=max_tokens
        )

        response = await self.chat_completion(request)
        return response.choices[0].message.content

    async def chat_with_system_prompt(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "openai/gpt-oss-20b",
        temperature: float = 0.7,
        max_tokens: int = 150
    ) -> str:
        request = ChatRequest(
            model=model,
            messages=[
                ChatMessage(role=ChatRole.SYSTEM, content=system_prompt),
                ChatMessage(role=ChatRole.USER, content=user_message)
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )

        response = await self.chat_completion(request)
        return response.choices[0].message.content

    async def multi_turn_chat(
        self,
        messages: List[ChatMessage],
        model: str = "openai/gpt-oss-20b",
        temperature: float = 0.7,
        max_tokens: int = 150
    ) -> str:
        request = ChatRequest(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )

        response = await self.chat_completion(request)
        return response.choices[0].message.content

    async def health_check(self) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.client.health_check)


groq_service = GroqService()