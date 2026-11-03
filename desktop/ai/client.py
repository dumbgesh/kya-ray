"""
desktop/ai/client.py - Local Ollama API client and response handling.

Provides:
- ExplanationResponse named tuple/data structure
- Sanitization of Ollama performance metrics
- Prerequisites check (API reachable and model pulled)
- Synchronous inference request with post-processing (preamble stripping, quote cleaning, sentence truncation protection)
- OllamaClient class encapsulation
"""

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from desktop.ai.prompts import build_intent_prompt, clean_truncated_sentence
from desktop.core.intents import (
    detect_create_quantity,
    extract_single_creation_output,
    infer_intent,
    strip_conversational_preamble,
    strip_surrounding_quotes,
)
from desktop.utils.config import OLLAMA_API_URL, OLLAMA_MODEL, REQUEST_TIMEOUT_SECONDS

ALLOWED_METRIC_KEYS = (
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
    "prompt_eval_count",
    "eval_count",
)


class ExplanationResponse(tuple):
    """
    3-tuple (success, content, metrics) preserving complete backward compatibility,
    while also exposing .intent, .success, .content, and .metrics as attributes/properties.
    """
    def __new__(cls, success: bool, content: str, metrics: Optional[Dict[str, Any]] = None, intent: str = "-explain"):
        obj = super().__new__(cls, (success, content, metrics))
        obj.intent = intent
        return obj

    @property
    def success(self) -> bool:
        return self[0]

    @property
    def content(self) -> str:
        return self[1]

    @property
    def metrics(self) -> Optional[Dict[str, Any]]:
        return self[2]


def sanitize_ollama_metrics(raw_metrics: Any) -> Optional[Dict[str, Any]]:
    """
    Extracts and sanitizes ONLY numeric timing and token count metadata.
    Guarantees strict privacy: zero user text, prompt, or response content is kept.
    Missing, non-numeric, or negative fields are stored as None (unavailable).
    """
    if not isinstance(raw_metrics, dict):
        return None
    sanitized: Dict[str, Any] = {}
    for key in ALLOWED_METRIC_KEYS:
        val = raw_metrics.get(key)
        # Ensure only numbers (int/float, excluding bool) >= 0 are accepted
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
            sanitized[key] = val
        else:
            sanitized[key] = None
    return sanitized


def check_ollama_prerequisites(
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 3.0,
) -> Tuple[str, str]:
    """
    Non-blocking check for Ollama API availability and the required model.
    Does NOT download models automatically. Returns (status, message).
    Status is one of: "ready", "model_missing", "offline".
    """
    target_model = model or OLLAMA_MODEL
    tags_url = (api_url or OLLAMA_API_URL).rsplit("/api/", 1)[0] + "/api/tags"

    try:
        req = urllib.request.Request(tags_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                found = any(target_model in m for m in models)
                if found:
                    return "ready", f"Ollama is running with {target_model}."
                return "model_missing", (
                    f"Ollama is running, but model '{target_model}' was not found.\n\n"
                    f"Please run 'ollama pull {target_model}' in your terminal."
                )
    except urllib.error.URLError:
        return "offline", (
            f"Could not connect to Ollama ({tags_url}).\n\n"
            "Please launch the Ollama desktop application."
        )
    except Exception as e:
        return "offline", f"Ollama check failed: {e}"
    return "offline", "Ollama is not reachable."


def request_ai_explanation(
    text: str,
    intent: Optional[str] = None,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
) -> ExplanationResponse:
    """
    Sends text to the local Ollama API to generate a concise response
    tailored to the inferred or specified intent (-explain, -summarize, -code, -create).

    Returns:
        ExplanationResponse (success: bool, content: str, metrics: dict | None)
        with .intent attribute denoting the intent applied.
    """
    target_intent = intent if intent is not None else infer_intent(text)
    target_url = api_url or OLLAMA_API_URL
    target_model = model or OLLAMA_MODEL
    request_timeout = timeout if timeout is not None else REQUEST_TIMEOUT_SECONDS

    prompt = build_intent_prompt(text, target_intent)

    payload = {
        "model": target_model,
        "prompt": prompt,
        "stream": False,  # Request the complete response at once
        "think": False,
        "options": {
            "num_predict": 90,
            "temperature": 0.1,
        },
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        target_url,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=request_timeout) as response:
            if response.status == 200:
                raw_body = response.read().decode("utf-8")
                parsed_json = json.loads(raw_body)
                raw_explanation = parsed_json.get("response", "").strip()
                if target_intent == "-create":
                    raw_explanation = strip_conversational_preamble(raw_explanation)
                    qty, is_multiple = detect_create_quantity(text)
                    if not is_multiple and qty == 1:
                        raw_explanation = extract_single_creation_output(raw_explanation)
                cleaned_quotes = strip_surrounding_quotes(raw_explanation)
                explanation = clean_truncated_sentence(cleaned_quotes)
                metrics = sanitize_ollama_metrics(parsed_json)

                if explanation:
                    return ExplanationResponse(True, explanation, metrics, intent=target_intent)
                return ExplanationResponse(False, "Ollama returned an empty response.", None, intent=target_intent)
            else:
                return ExplanationResponse(
                    False, f"Ollama HTTP {response.status}: {response.reason}", None, intent=target_intent
                )

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return ExplanationResponse(
                False,
                f"Model '{target_model}' was not found in Ollama. Run 'ollama pull {target_model}'.",
                None,
                intent=target_intent,
            )
        return ExplanationResponse(
            False, f"Ollama HTTP error {error.code}: {error.reason}", None, intent=target_intent
        )

    except urllib.error.URLError:
        return ExplanationResponse(
            False,
            f"Could not connect to Ollama at {target_url}. Please ensure the Ollama app is running.",
            None,
            intent=target_intent,
        )

    except TimeoutError:
        return ExplanationResponse(
            False,
            f"Request timed out after {request_timeout}s waiting for Ollama to respond.",
            None,
            intent=target_intent,
        )

    except Exception as error:
        return ExplanationResponse(
            False, f"Unexpected error while contacting Ollama: {error}", None, intent=target_intent
        )


class OllamaClient:
    """Encapsulated Ollama AI client class."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.api_url = api_url or OLLAMA_API_URL
        self.model = model or OLLAMA_MODEL
        self.timeout = timeout if timeout is not None else REQUEST_TIMEOUT_SECONDS

    def check_prerequisites(self) -> Tuple[str, str]:
        """Check whether Ollama is reachable and model is available."""
        return check_ollama_prerequisites(self.api_url, self.model, timeout=min(self.timeout, 3.0))

    def generate(self, text: str, intent: Optional[str] = None) -> ExplanationResponse:
        """Generate response for given text with optional intent override."""
        return request_ai_explanation(
            text=text,
            intent=intent,
            api_url=self.api_url,
            model=self.model,
            timeout=self.timeout,
        )

