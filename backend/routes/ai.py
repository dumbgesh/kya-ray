"""
backend/routes/ai.py - AI generation and streaming endpoints.
"""

import json
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.services.ai_provider import AIProvider, AIResponse
from backend.services.groq_client import GroqProvider, GroqRateLimitError
from desktop.core.intents import CORE_INTENTS, infer_intent

router = APIRouter()


def sanitize_error_message(msg: Any) -> str:
    """Strips API keys, bearer tokens, and internal paths from user-visible error strings."""
    if not msg:
        return ""
    text = str(msg)
    # Mask Groq API keys (gsk_...)
    text = re.sub(r"gsk_[A-Za-z0-9_-]+", "gsk_***", text)
    # Mask Bearer tokens
    text = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer ***", text, flags=re.IGNORECASE)
    return text


class GenerateRequest(BaseModel):
    """Request payload for AI response generation."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=get_settings().MAX_INPUT_LENGTH,
        description="Selected text highlighted by the user.",
    )
    intent: Optional[str] = Field(
        default=None,
        description="Optional intent override (-explain, -summarize, -code, -create). Auto-detected if omitted.",
    )


class GenerateResponse(BaseModel):
    """Response payload containing generated text and metadata."""

    success: bool
    content: str
    intent: str
    model: str
    usage: Optional[Dict[str, Any]] = None


# Dependency injection for AI provider (allows easy mocking in tests)
_default_provider: Optional[AIProvider] = None


def get_ai_provider() -> AIProvider:
    """Dependency provider yielding the configured AIProvider instance."""
    global _default_provider
    if _default_provider is None:
        _default_provider = GroqProvider()
    return _default_provider


def set_ai_provider(provider: AIProvider):
    """Overrides the default AIProvider instance (useful for test mocks)."""
    global _default_provider
    _default_provider = provider


@router.post(
    "/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a complete AI response",
    description="Processes highlighted text using the configured LLM and returns a clean, intent-tailored response.",
)
async def generate_response(
    request: GenerateRequest,
    provider: AIProvider = Depends(get_ai_provider),
):
    cleaned_text = request.text.strip()
    if not cleaned_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Input text cannot be empty or whitespace only.",
        )

    # Automatic intent detection if not explicitly specified or invalid
    if request.intent and request.intent in CORE_INTENTS:
        target_intent = request.intent
    else:
        target_intent = infer_intent(cleaned_text)

    try:
        result: AIResponse = await provider.generate(cleaned_text, target_intent)
        return GenerateResponse(
            success=result.success,
            content=result.content,
            intent=result.intent,
            model=result.model,
            usage=result.usage,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=sanitize_error_message(e)) from e
    except ConnectionError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=sanitize_error_message(e)) from e
    except RuntimeError as e:
        safe_msg = sanitize_error_message(e)
        if "rate limit" in safe_msg.lower():
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=safe_msg) from e
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=safe_msg) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=sanitize_error_message(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {sanitize_error_message(e)}",
        ) from e


@router.post(
    "/stream",
    summary="Stream an AI response",
    description="Streams Server-Sent Events (SSE) chunks for real-time response rendering.",
)
async def stream_response(
    raw_request: Request,
    request: GenerateRequest,
    provider: AIProvider = Depends(get_ai_provider),
):
    cleaned_text = request.text.strip()
    if not cleaned_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Input text cannot be empty or whitespace only.",
        )

    if request.intent and request.intent in CORE_INTENTS:
        target_intent = request.intent
    else:
        target_intent = infer_intent(cleaned_text)

    async def event_generator():
        stream_gen = None
        try:
            stream_gen = provider.stream(cleaned_text, target_intent)
            async for chunk in stream_gen:
                if await raw_request.is_disconnected():
                    break
                payload = json.dumps({"chunk": chunk, "intent": target_intent})
                yield f"data: {payload}\n\n"
            else:
                yield "data: [DONE]\n\n"
        except GroqRateLimitError as e:
            err = json.dumps({"error": sanitize_error_message(e), "status": 429})
            yield f"data: {err}\n\n"
        except PermissionError as e:
            err = json.dumps({"error": sanitize_error_message(e), "status": 401})
            yield f"data: {err}\n\n"
        except ConnectionError as e:
            err = json.dumps({"error": sanitize_error_message(e), "status": 503})
            yield f"data: {err}\n\n"
        except RuntimeError as e:
            safe_msg = sanitize_error_message(e)
            status_code = 429 if "rate limit" in safe_msg.lower() else 502
            err = json.dumps({"error": safe_msg, "status": status_code})
            yield f"data: {err}\n\n"
        except Exception as e:
            safe_msg = sanitize_error_message(e)
            status_code = 429 if "rate limit" in safe_msg.lower() else 500
            err = json.dumps({"error": safe_msg, "status": status_code})
            yield f"data: {err}\n\n"
        finally:
            if stream_gen is not None and hasattr(stream_gen, "aclose"):
                try:
                    await stream_gen.aclose()
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

