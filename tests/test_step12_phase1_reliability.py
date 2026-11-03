"""
tests/test_step12_phase1_reliability.py - Tests for Kya-Ray Step 12 Phase 1 Reliability Fixes.

Covers:
1. Windows console cp1252/cp437 startup encoding safety.
2. Backend process lifecycle management (adoption, auto-spawn, crash detection, clean shutdown).
3. GroqCloud rate limit status 429 mapping and user-friendly error display.
4. Upstream streaming cancellation upon client disconnect.
"""

import asyncio
import io
import json
import os
import subprocess
import threading
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes.ai import get_ai_provider, router as ai_router
from backend.services.ai_provider import AIProvider, AIResponse
from backend.services.groq_client import GroqProvider, GroqRateLimitError
from desktop.ai.backend_client import BackendClient
from desktop.core.backend_manager import BackendProcessManager
from desktop.utils.logger import SafeOutput


# ============================================================================
# 1. Windows Startup & Console Encoding Tests
# ============================================================================

def test_safe_output_handles_cp1252_encoding_errors(tmp_path):
    """Verify SafeOutput falls back gracefully on cp1252/cp437 unencodable characters."""
    class MockCp1252Stream:
        def __init__(self):
            self.written = []

        def write(self, s: str):
            # Simulate a cp1252 Windows console raising UnicodeEncodeError
            try:
                s.encode("cp1252")
            except UnicodeEncodeError as exc:
                raise exc
            self.written.append(s)

        def flush(self):
            pass

    mock_stream = MockCp1252Stream()
    safe_out = SafeOutput(mock_stream, log_path=str(tmp_path / "test_out.log"))

    # Unicode character not present in cp1252 (e.g. \u2715 multiplication cross)
    test_str = "Status: [✕] Failed\n"
    safe_out.write(test_str)

    # Must not raise, and replaced string should have been written
    assert len(mock_stream.written) > 0
    assert "?" in mock_stream.written[0] or "Failed" in mock_stream.written[0]


def test_app_py_has_no_unsafe_unicode_symbols():
    """Ensure desktop/app.py uses ASCII safe status icons like [X] instead of unicode cross."""
    app_py_path = os.path.join(os.path.dirname(__file__), "..", "desktop", "app.py")
    with open(app_py_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "\u2715" not in content, "Found unicode multiplication cross in desktop/app.py"


# ============================================================================
# 2. Backend Process Lifecycle Management Tests
# ============================================================================

def test_backend_manager_adopts_existing_running_instance():
    """If backend is already healthy, manager adopts it without spawning a subprocess."""
    mock_client = MagicMock()
    mock_client.check_health.return_value = ("ready", "Healthy")

    manager = BackendProcessManager(client=mock_client)
    success, msg = manager.ensure_running()

    assert success is True
    assert "existing" in msg.lower()
    assert manager.is_owned is False
    assert manager.process is None
    # Stop should not attempt to kill any process
    manager.stop()
    assert manager.is_running is True


@patch("subprocess.Popen")
def test_backend_manager_spawns_process_when_backend_not_running(mock_popen):
    """If backend is offline, manager spawns a subprocess and waits for /health."""
    mock_client = MagicMock()
    # First offline, then ready after spawn
    mock_client.check_health.side_effect = [
        ("offline", "Not running"),
        ("ready", "Healthy"),
    ]

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None  # Process is running
    fake_proc.pid = 99999
    mock_popen.return_value = fake_proc

    manager = BackendProcessManager(client=mock_client, startup_timeout=2.0, poll_interval=0.01)
    success, msg = manager.ensure_running()

    assert success is True
    assert "successfully" in msg.lower()
    assert manager.is_owned is True
    assert manager.process is fake_proc
    mock_popen.assert_called_once()

    # Clean shutdown should terminate the owned process
    manager.stop()
    fake_proc.terminate.assert_called_once()
    assert manager.process is None
    assert manager.is_owned is False


@patch("subprocess.Popen")
def test_backend_manager_handles_immediate_process_crash(mock_popen):
    """If spawned backend crashes immediately, manager detects non-zero exit code."""
    mock_client = MagicMock()
    mock_client.check_health.return_value = ("offline", "Not running")

    fake_proc = MagicMock()
    fake_proc.poll.return_value = 1  # Crashed with code 1
    fake_proc.returncode = 1
    fake_proc.pid = 88888
    mock_popen.return_value = fake_proc

    manager = BackendProcessManager(client=mock_client, startup_timeout=1.0, poll_interval=0.01)
    success, msg = manager.ensure_running()

    assert success is False
    assert "terminated unexpectedly" in msg.lower()
    assert manager.is_owned is False
    assert manager.process is None


def test_backend_manager_does_not_kill_unowned_processes():
    """Verify stop() is a no-op if manager did not spawn the backend."""
    mock_client = MagicMock()
    mock_client.check_health.return_value = ("ready", "Healthy")

    manager = BackendProcessManager(client=mock_client)
    manager.ensure_running()
    assert manager.is_owned is False

    # Calling stop should be safe and harmless
    manager.stop()
    assert manager.process is None


# ============================================================================
# 3. Groq Rate Limit Mapping & Error Handling Tests
# ============================================================================

def test_generate_endpoint_maps_rate_limit_to_http_429():
    """POST /generate should return HTTP 429 when Groq rate limit is hit."""
    test_app = FastAPI()
    test_app.include_router(ai_router, prefix="/api/v1/ai")

    class RateLimitingProvider(AIProvider):
        async def generate(self, text: str, intent: str) -> AIResponse:
            raise GroqRateLimitError("Rate limit reached: tokens per minute exceeded")

        async def stream(self, text: str, intent: str) -> AsyncIterator[str]:
            yield "unused"

        def is_configured(self) -> bool:
            return True

    test_app.dependency_overrides[get_ai_provider] = lambda: RateLimitingProvider()

    with TestClient(test_app) as client:
        resp = client.post("/api/v1/ai/generate", json={"text": "hello", "intent": "-explain"})
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["detail"].lower()


def test_stream_endpoint_maps_rate_limit_to_sse_429():
    """POST /stream should emit SSE error payload with status 429 on rate limit."""
    test_app = FastAPI()
    test_app.include_router(ai_router, prefix="/api/v1/ai")

    class RateLimitingStreamProvider(AIProvider):
        async def generate(self, text: str, intent: str) -> AIResponse:
            return AIResponse(success=True, content="ok", intent=intent, model="test")

        async def stream(self, text: str, intent: str) -> AsyncIterator[str]:
            # Simulate initial token followed by rate limit exception
            yield "Hello "
            raise GroqRateLimitError("Rate limit exceeded")

        def is_configured(self) -> bool:
            return True

    test_app.dependency_overrides[get_ai_provider] = lambda: RateLimitingStreamProvider()

    with TestClient(test_app) as client:
        resp = client.post("/api/v1/ai/stream", json={"text": "hello", "intent": "-explain"})
        assert resp.status_code == 200
        lines = [line.strip() for line in resp.text.split("\n") if line.startswith("data:")]
        # Last line should contain error with status 429
        last_event = json.loads(lines[-1].replace("data:", "").strip())
        assert last_event.get("status") == 429
        assert "rate limit" in last_event.get("error", "").lower()


def test_desktop_backend_client_parses_429_sse_rate_limit():
    """Desktop BackendClient.stream() transforms status 429 SSE into clear user notification."""
    client = BackendClient(base_url="http://mock-backend")

    sse_data = [
        b'data: {"chunk": "Some initial text", "intent": "-explain"}\n\n',
        b'data: {"error": "Rate limit exceeded: 30 RPM", "status": 429}\n\n',
    ]

    with patch("httpx.Client.stream") as mock_stream_ctx:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = [line.decode("utf-8") for line in sse_data]
        mock_stream_ctx.return_value.__enter__.return_value = mock_resp

        chunks = list(client.stream("Explain this"))

        assert len(chunks) == 2
        assert chunks[0] == "Some initial text"
        assert "[Error: GroqCloud rate limit exceeded. Please wait a moment before trying again.]" in chunks[1]


# ============================================================================
# 4. Upstream Groq Stream Cancellation Tests
# ============================================================================

def test_groq_provider_stream_calls_close_on_upstream_response():
    """Verify GroqProvider.stream() closes the upstream stream_response on completion or exit."""
    async def _test():
        mock_async_groq = MagicMock()
        mock_stream_resp = MagicMock()
        mock_stream_resp.close = MagicMock()

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock(delta=MagicMock(content="token1"))]
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock(delta=MagicMock(content="token2"))]

        async def mock_async_iter():
            yield chunk1
            yield chunk2

        mock_stream_resp.__aiter__.side_effect = mock_async_iter
        mock_async_groq.chat.completions.create = AsyncMock(return_value=mock_stream_resp)

        provider = GroqProvider(api_key="gsk_test", client=mock_async_groq)

        tokens = []
        async for token in provider.stream("hello", "-explain"):
            tokens.append(token)

        assert tokens == ["token1", "token2"]
        mock_stream_resp.close.assert_called_once()

    asyncio.run(_test())


def test_groq_provider_stream_calls_close_on_generator_aclose():
    """Verify when consumer calls aclose() early on stream generator, upstream close() is invoked."""
    async def _test():
        mock_async_groq = MagicMock()
        mock_stream_resp = MagicMock()
        mock_stream_resp.close = MagicMock()

        async def infinite_chunks():
            for i in range(100):
                c = MagicMock()
                c.choices = [MagicMock(delta=MagicMock(content=f"tok_{i}"))]
                yield c

        mock_stream_resp.__aiter__.side_effect = infinite_chunks
        mock_async_groq.chat.completions.create = AsyncMock(return_value=mock_stream_resp)

        provider = GroqProvider(api_key="gsk_test", client=mock_async_groq)

        gen = provider.stream("hello", "-explain")
        first_tok = await gen.__anext__()
        assert first_tok == "tok_0"

        # Client cancels / disconnects
        await gen.aclose()

        # Upstream close must have been called
        mock_stream_resp.close.assert_called_once()

    asyncio.run(_test())
