from typing import Any
from pydantic import BaseModel


class Message(BaseModel):
    role: str  # "user" | "assistant"
    content: Any  # str or list of content blocks


class ChatRequest(BaseModel):
    messages: list[Message] = []  # prior conversation history
    user_message: str


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = {}
