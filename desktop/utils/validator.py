"""
desktop/utils/validator.py - Live GroqCloud API Key Validation.

Performs a minimal authenticated request against the Groq API (GET /openai/v1/models)
to ensure only verified, working credentials are saved to Windows Credential Manager.
Distinguishes between invalid keys, network errors, rate limits, and provider outages.
"""

from typing import Tuple
import httpx


def validate_groq_api_key(api_key: str, timeout: float = 8.0) -> Tuple[bool, str]:
    """
    Validates a Groq API key by querying the lightweight models endpoint.
    Returns: (is_valid: bool, error_message: str)
    """
    cleaned = (api_key or "").strip()
    if not cleaned:
        return False, "Please enter an API key."

    if not cleaned.startswith("gsk_"):
        return False, "Invalid key format. Groq API keys start with 'gsk_'."

    try:
        resp = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {cleaned}"},
            timeout=timeout,
        )
        if resp.status_code == 200:
            return True, ""
        elif resp.status_code == 401:
            return False, "Invalid API key. Please check your key on Groq console."
        elif resp.status_code == 429:
            return False, "Rate limit reached. Please wait a moment and try again."
        elif resp.status_code >= 500:
            return False, "Groq service is temporarily unavailable. Please try again later."
        else:
            return False, f"Validation failed (HTTP {resp.status_code})."
    except (httpx.ConnectError, httpx.NetworkError):
        return False, "Could not connect to Groq. Please check your internet connection."
    except httpx.TimeoutException:
        return False, "Connection timed out contacting Groq. Please check your connection."
    except Exception as e:
        return False, f"Error validating key: {e}"

