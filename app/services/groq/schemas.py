from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


class ChatRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: ChatRole
    content: str


class ChatRequest(BaseModel):
    model: str = Field(default="openai/gpt-oss-20b")
    messages: List[ChatMessage]
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=150, ge=1, le=4096)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    stream: bool = Field(default=False)


class ChatResponseUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatResponseChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


class ChatResponse(BaseModel):
    id: str
    object: str
    created: int
    model: str
    choices: List[ChatResponseChoice]
    usage: ChatResponseUsage


class GroqError(BaseModel):
    error: str
    details: Optional[Dict[str, Any]] = None