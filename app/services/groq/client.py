import logging
from typing import Optional
from groq import Groq
from app.core.config import settings
from .models import ChatRequest, ChatResponse, GroqError

logger = logging.getLogger(__name__)


class GroqClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GROQ_API_KEY
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is required")

        self.client = Groq(api_key=self.api_key)
        logger.info("GroqClient initialized")

    def chat_completion(self, request: ChatRequest) -> ChatResponse:
        try:
            logger.debug(f"Making chat completion request with model: {request.model}")

            messages = [{"role": msg.role.value, "content": msg.content} for msg in request.messages]

            completion = self.client.chat.completions.create(
                model=request.model,
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                top_p=request.top_p,
                stream=request.stream
            )

            response = ChatResponse(
                id=completion.id,
                object=completion.object,
                created=completion.created,
                model=completion.model,
                choices=[
                    {
                        "index": choice.index,
                        "message": {
                            "role": choice.message.role,
                            "content": choice.message.content
                        },
                        "finish_reason": choice.finish_reason
                    }
                    for choice in completion.choices
                ],
                usage={
                    "prompt_tokens": completion.usage.prompt_tokens,
                    "completion_tokens": completion.usage.completion_tokens,
                    "total_tokens": completion.usage.total_tokens
                }
            )

            logger.debug(f"Chat completion successful, tokens used: {response.usage.total_tokens}")
            return response

        except Exception as e:
            logger.error(f"Error in chat completion: {e}")
            raise Exception(f"Groq API error: {str(e)}")

    def health_check(self) -> bool:
        try:
            test_request = ChatRequest(
                model="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=5
            )
            self.chat_completion(test_request)
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False