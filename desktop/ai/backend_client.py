"""
desktop/ai/backend_client.py - Client for Kya-Ray Cloud Backend (FastAPI).

Communicates with the local or remote FastAPI cloud backend using HTTPX:
- Health check query
- Non-streaming full response generation
- Real-time Server-Sent Events (SSE) streaming with cancellation support
- Automatic retry / connection failure handling
"""

import json
import threading
from typing import Any, Dict, Iterator, Optional, Tuple

import httpx

from desktop.core.intents import infer_intent
from desktop.utils.config import BACKEND_BASE_URL, REQUEST_TIMEOUT_SECONDS


class BackendResponse:
    """Standardized response from Kya-Ray Cloud Backend."""

    def __init__(
        self,
        success: bool,
        content: str,
        intent: str = "-explain",
        model: str = "",
        usage: Optional[Dict[str, Any]] = None,
    ):
        self.success = success
        self.content = content
        self.intent = intent
        self.model = model
        self.usage = usage

    def __repr__(self):
        return f"<BackendResponse success={self.success} intent={self.intent} content={self.content[:30]!r}>"


class BackendClient:
    """Client for FastAPI AI Cloud Backend with persistent connection pooling."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = (base_url or BACKEND_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else float(REQUEST_TIMEOUT_SECONDS)
        self._lock = threading.Lock()
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        """Returns or lazily creates the pooled HTTP client."""
        with self._lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.Client(
                    timeout=httpx.Timeout(self.timeout, connect=5.0),
                    limits=httpx.Limits(max_keepalive_connections=5, max_connections=15, keepalive_expiry=30.0),
                )
            return self._client

    def close(self) -> None:
        """Closes the persistent HTTP client and releases connection pool sockets."""
        with self._lock:
            if self._client is not None and not self._client.is_closed:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def check_health(self, timeout: float = 3.0) -> Tuple[str, str]:
        """
        Fast health probe to determine if backend is running and Groq is ready.
        Returns: (status: str, message: str)
          - status: "ready" | "groq_unconfigured" | "offline"
        """
        health_url = f"{self.base_url}/health"
        try:
            client = self._get_client()
            resp = client.get(health_url, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                groq_ok = data.get("groq_configured", False)
                model_name = data.get("model", "Groq")
                if groq_ok:
                    return "ready", f"Cloud backend is running with {model_name}."
                return "groq_unconfigured", (
                    "Backend is reachable, but GROQ_API_KEY is not configured.\n\n"
                    "Please set GROQ_API_KEY in the backend .env file."
                )
            return "offline", f"Backend returned HTTP {resp.status_code}: {resp.reason_phrase}"
        except (httpx.ConnectError, httpx.NetworkError):
            return "offline", (
                f"Could not connect to Kya-Ray Cloud Backend at {self.base_url}.\n\n"
                "Please start the backend server:\n"
                "  uvicorn backend.main:app --port 8000"
            )
        except httpx.TimeoutException:
            return "offline", f"Health check timed out contacting backend at {self.base_url}."
        except Exception as e:
            return "offline", f"Backend check error: {e}"

    def check_prerequisites(self) -> Tuple[str, str]:
        """Compatibility alias for orchestrator prerequisite check."""
        return self.check_health(timeout=3.0)

    def generate(self, text: str, intent: Optional[str] = None) -> BackendResponse:
        """
        Requests complete AI response from backend POST /api/v1/ai/generate.
        """
        target_intent = intent if intent is not None else infer_intent(text)
        endpoint = f"{self.base_url}/api/v1/ai/generate"
        payload = {"text": text, "intent": target_intent}

        try:
            client = self._get_client()
            resp = client.post(endpoint, json=payload)

            if resp.status_code == 200:
                data = resp.json()
                return BackendResponse(
                    success=data.get("success", True),
                    content=data.get("content", ""),
                    intent=data.get("intent", target_intent),
                    model=data.get("model", ""),
                    usage=data.get("usage"),
                )

            if resp.status_code == 401:
                return BackendResponse(
                    success=False,
                    content="Backend authentication error: Invalid or missing Groq API key on backend.",
                    intent=target_intent,
                )

            if resp.status_code == 429:
                return BackendResponse(
                    success=False,
                    content="GroqCloud rate limit exceeded. Please wait a moment before trying again.",
                    intent=target_intent,
                )

            error_detail = ""
            try:
                error_detail = resp.json().get("detail", resp.text)
            except Exception:
                error_detail = resp.text

            return BackendResponse(
                success=False,
                content=f"Backend HTTP {resp.status_code}: {error_detail}",
                intent=target_intent,
            )

        except (httpx.ConnectError, httpx.NetworkError):
            return BackendResponse(
                success=False,
                content=(
                    f"Could not connect to Kya-Ray Cloud Backend at {self.base_url}.\n\n"
                    "Please ensure the backend is running:\n"
                    "  uvicorn backend.main:app --port 8000"
                ),
                intent=target_intent,
            )
        except httpx.TimeoutException:
            return BackendResponse(
                success=False,
                content=f"Request timed out after {self.timeout}s waiting for cloud backend.",
                intent=target_intent,
            )
        except Exception as e:
            return BackendResponse(
                success=False,
                content=f"Unexpected error contacting backend: {e}",
                intent=target_intent,
            )

    def stream(
        self,
        text: str,
        intent: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[str]:
        """
        Streams response chunks from backend POST /api/v1/ai/stream via SSE.
        Yields chunk tokens in real-time. Halts cleanly if cancel_event is set.
        """
        target_intent = intent if intent is not None else infer_intent(text)
        endpoint = f"{self.base_url}/api/v1/ai/stream"
        payload = {"text": text, "intent": target_intent}

        try:
            client = self._get_client()
            with client.stream("POST", endpoint, json=payload) as response:
                if response.status_code != 200:
                    yield f"Backend error ({response.status_code}): {response.reason_phrase}"
                    return

                for line in response.iter_lines():
                    if cancel_event and cancel_event.is_set():
                        break

                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue

                    data_content = line[len("data:"):].strip()
                    if data_content == "[DONE]":
                        break

                    try:
                        parsed = json.loads(data_content)
                        if "chunk" in parsed:
                            yield parsed["chunk"]
                        elif "error" in parsed:
                            status = parsed.get("status")
                            err_msg = str(parsed.get("error", ""))
                            if status == 429 or "rate limit" in err_msg.lower():
                                yield "\n\n[Error: GroqCloud rate limit exceeded. Please wait a moment before trying again.]"
                            elif status == 401:
                                yield "\n\n[Error: Backend authentication error: Invalid or missing Groq API key.]"
                            else:
                                yield f"\n\n[Error: {err_msg}]"
                            break
                    except json.JSONDecodeError:
                        continue

        except (httpx.ConnectError, httpx.NetworkError):
            yield (
                f"Could not connect to Kya-Ray Cloud Backend at {self.base_url}. "
                "Please ensure the backend is running."
            )
        except httpx.TimeoutException:
            yield f"Streaming timed out after {self.timeout}s."
        except Exception as e:
            yield f"Error during streaming: {e}"

