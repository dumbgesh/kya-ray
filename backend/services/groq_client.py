"""
backend/services/groq_client.py - GroqCloud AI Provider implementation.

Integrates GroqCloud using the official Python SDK (groq.AsyncGroq).
Features:
- Configurable model via environment (GROQ_MODEL)
- Streaming and non-streaming inference
- Strict privacy: Zero logging of selected text, prompts, or model completions
- Comprehensive error handling and status code mapping
"""

import time
from typing import Any, AsyncIterator, Dict, List, Optional

import groq
from groq import AsyncGroq

from backend.config import get_settings
from backend.services.ai_provider import AIProvider, AIResponse
from desktop.ai.prompts import build_intent_prompt, clean_truncated_sentence
from desktop.core.intents import (
    detect_create_quantity,
    extract_single_creation_output,
    strip_conversational_preamble,
    strip_surrounding_quotes,
)


class GroqRateLimitError(RuntimeError):
    """Raised specifically when GroqCloud rate limits are reached."""
    pass


SYSTEM_REASONING_PROMPT = (
    "You are Kya-Ray, an intelligent, accurate, and concise desktop AI companion.\n\n"
    "### Core Reasoning Principles:\n"
    "1. Deep Comprehension: Understand the structure, domain, and context of the selected input before formulating a response.\n"
    "2. Objective Inference: Discern the user's real objective—distinguish between mere passive description, rigorous analysis/code review, debugging, solving, and creative drafting.\n"
    "3. Consequence & Assumption Reasoning: Evaluate underlying assumptions, boundary conditions, logical relationships, and downstream consequences.\n"
    "4. Adaptive Uncertainty: When an input is genuinely ambiguous, make the most reasonable interpretation for obvious cases without badgering; state concise clarification or uncertainty only when alternate interpretations would materially change the result. Never pretend certainty when information is missing or unverifiable.\n\n"
    "### Task Verification Standards:\n"
    "- Code: Inspect execution flow and control paths accurately. Proportionality: Scale response length to snippet complexity—concise for short functions, detailed only when warranted. Accuracy: Analyse only the provided code without inventing syntax errors, runtime errors, or phantom warnings. Distinguish confirmed defects (e.g. division by zero, unbound variables on empty input, resource leaks) from potential improvements. If code is valid, state so clearly without inventing issues. Suggest concrete, actionable fixes. Never claim code was executed unless tool output is present.\n"
    "- Mathematics: Verify step-by-step arithmetic and algebraic logic, check assumptions, ensure units are consistent, and verify final numerical answers.\n"
    "- Data: Verify schema structures, relational integrity, and inconsistencies without hallucinating missing data points.\n"
    "- Creation & Rewriting: Fulfill the user's intended objective while preserving essential tone and meaning, without conversational preamble.\n"
    "- Explanation & Summary: Distinguish claims from verified facts, preserve vital nuance/metrics, and match the complexity of the input."
)


class GroqProvider(AIProvider):
    """GroqCloud inference provider."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[AsyncGroq] = None,
    ):
        settings = get_settings()
        self.api_key = api_key
        self.model = model or settings.GROQ_MODEL
        self.timeout = timeout if timeout is not None else settings.REQUEST_TIMEOUT_SECONDS
        self._client = client
        self._custom_client = client is not None
        self._active_key = None

    def _get_api_key(self) -> str:
        """Retrieves active API key from explicit init, Windows Credential Manager, or settings."""
        if self.api_key is not None:
            return self.api_key
        try:
            from desktop.utils.credentials import get_stored_api_key
            stored = get_stored_api_key()
            if stored:
                return stored
        except Exception:
            pass
        return get_settings().GROQ_API_KEY

    def _get_client(self) -> AsyncGroq:
        """Lazily creates and returns the AsyncGroq client."""
        if self._client is not None and getattr(self, "_custom_client", False):
            return self._client

        effective_key = self._get_api_key()
        if not effective_key:
            raise ValueError("GROQ_API_KEY is not configured on the backend.")
        if self._client is None or self._active_key != effective_key:
            self._client = AsyncGroq(api_key=effective_key, timeout=self.timeout)
            self._active_key = effective_key
        return self._client

    def is_configured(self) -> bool:
        """Checks if a valid Groq API key is present."""
        key = self._get_api_key()
        return bool(key and key.strip())

    async def close(self) -> None:
        """Closes the underlying AsyncGroq client and releases HTTP connection pool."""
        if self._client is not None:
            try:
                close_res = self._client.close()
                if hasattr(close_res, "__await__"):
                    await close_res
            except Exception:
                pass
            self._client = None

    def _build_messages(self, text: str, intent: str) -> List[Dict[str, str]]:
        """Constructs system and user message payload adhering to Kya-Ray intent rules."""
        prompt = build_intent_prompt(text, intent)
        return [
            {
                "role": "system",
                "content": SYSTEM_REASONING_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

    async def generate(self, text: str, intent: str) -> AIResponse:
        """Performs non-streaming GroqCloud inference."""
        client = self._get_client()
        messages = self._build_messages(text, intent)

        start_time = time.perf_counter()
        try:
            completion = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
                max_tokens=384,
                stream=False,
            )
            duration = time.perf_counter() - start_time

            raw_text = completion.choices[0].message.content or ""
            raw_text = raw_text.strip()

            if intent == "-create":
                raw_text = strip_conversational_preamble(raw_text)
                qty, is_multiple = detect_create_quantity(text)
                if not is_multiple and qty == 1:
                    raw_text = extract_single_creation_output(raw_text)

            cleaned_quotes = strip_surrounding_quotes(raw_text)
            final_content = clean_truncated_sentence(cleaned_quotes)

            usage_info = None
            if completion.usage:
                usage_info = {
                    "prompt_tokens": completion.usage.prompt_tokens,
                    "completion_tokens": completion.usage.completion_tokens,
                    "total_tokens": completion.usage.total_tokens,
                    "duration_seconds": round(duration, 3),
                }

            return AIResponse(
                success=True,
                content=final_content,
                intent=intent,
                model=self.model,
                usage=usage_info,
            )

        except groq.AuthenticationError as e:
            raise PermissionError(f"GroqCloud authentication failed: {e}") from e
        except groq.RateLimitError as e:
            raise GroqRateLimitError(f"GroqCloud rate limit reached: {e}") from e
        except groq.APIConnectionError as e:
            raise ConnectionError(f"Failed to connect to GroqCloud API: {e}") from e
        except groq.APIStatusError as e:
            raise RuntimeError(f"GroqCloud API error ({e.status_code}): {e.message}") from e

    async def stream(self, text: str, intent: str) -> AsyncIterator[str]:
        """Performs streaming GroqCloud inference, yielding incremental chunks."""
        client = self._get_client()
        messages = self._build_messages(text, intent)
        stream_response = None

        try:
            stream_response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
                max_tokens=384,
                stream=True,
            )

            async for chunk in stream_response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except groq.AuthenticationError as e:
            raise PermissionError(f"GroqCloud authentication failed: {e}") from e
        except groq.RateLimitError as e:
            raise GroqRateLimitError(f"GroqCloud rate limit reached: {e}") from e
        except groq.APIConnectionError as e:
            raise ConnectionError(f"Failed to connect to GroqCloud API: {e}") from e
        except groq.APIStatusError as e:
            raise RuntimeError(f"GroqCloud API error ({e.status_code}): {e.message}") from e
        finally:
            if stream_response is not None and hasattr(stream_response, "close"):
                try:
                    close_res = stream_response.close()
                    if hasattr(close_res, "__await__"):
                        await close_res
                except Exception:
                    pass

