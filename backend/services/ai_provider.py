"""
backend/services/ai_provider.py - Abstract AI Provider Interface.

Defines the contract for AI providers to allow seamless swapping between
GroqCloud, local Ollama, Anthropic, Gemini, or OpenAI.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, Optional
from pydantic import BaseModel, Field


class AIResponse(BaseModel):
    """Structured response returned by any AI provider."""

    success: bool
    content: str
    intent: str
    model: str
    usage: Optional[Dict[str, Any]] = None


class AIProvider(ABC):
    """Abstract base provider for model inference."""

    @abstractmethod
    async def generate(self, text: str, intent: str) -> AIResponse:
        """Generates a complete response for the given text and intent."""
        pass

    @abstractmethod
    async def stream(self, text: str, intent: str) -> AsyncIterator[str]:
        """Streams chunk deltas for the given text and intent."""
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Returns True if the provider has necessary API credentials configured."""
        pass

    async def close(self) -> None:
        """Optional provider cleanup on application shutdown."""
        pass

