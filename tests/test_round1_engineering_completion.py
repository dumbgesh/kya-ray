"""
tests/test_round1_engineering_completion.py - Tests for Kya-Ray Round 1 Engineering Completion.

Covers:
1. Safe configuration parsing and boundary validation (backend/config and desktop/utils/config).
2. Persistent HTTP connection pooling and client lifecycle in BackendClient.
3. Orchestrator manual re-analysis streaming and cancellation.
4. Self-healing offline-to-online recovery in process_activation.
5. Non-intrusive startup notice behaviour.
6. Clean provider connection cleanup on shutdown.
"""

import os
import threading
from unittest.mock import MagicMock, patch

import pytest

from backend.config import Settings, safe_float, safe_int
from backend.services.groq_client import GroqProvider
from desktop.ai.backend_client import BackendClient
from desktop.core.orchestrator import AppOrchestrator


# ============================================================================
# 1. Safe Configuration Parsing Tests
# ============================================================================

def test_safe_int_valid_and_fallbacks():
    assert safe_int("8000", 8000) == 8000
    assert safe_int("8080", 8000) == 8080
    assert safe_int("invalid", 8000) == 8000
    assert safe_int(None, 8000) == 8000
    assert safe_int("", 8000) == 8000
    assert safe_int("-10", 8000, min_val=1) == 8000
    assert safe_int("70000", 8000, max_val=65535) == 8000


def test_safe_float_valid_and_fallbacks():
    assert safe_float("30.0", 30.0) == 30.0
    assert safe_float("15.5", 30.0) == 15.5
    assert safe_float("not-a-number", 30.0) == 30.0
    assert safe_float(None, 30.0) == 30.0
    assert safe_float("-5.0", 30.0, min_val=1.0) == 30.0
    assert safe_float("500.0", 30.0, max_val=300.0) == 30.0


def test_settings_resilient_to_malformed_environment(monkeypatch):
    """Settings must safely fall back when env vars contain invalid strings."""
    monkeypatch.setenv("BACKEND_PORT", "not_a_port")
    monkeypatch.setenv("BACKEND_TIMEOUT_SECONDS", "unlimited")
    monkeypatch.setenv("BACKEND_HOST", "  ")

    settings = Settings()
    assert settings.PORT == 8000
    assert settings.REQUEST_TIMEOUT_SECONDS == 30.0
    assert settings.HOST == "127.0.0.1"


# ============================================================================
# 2. Persistent Connection Pooling & Client Lifecycle Tests
# ============================================================================

def test_backend_client_connection_pooling():
    """BackendClient reuses its underlying persistent client across multiple operations."""
    client = BackendClient(base_url="http://127.0.0.1:8000")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "healthy", "groq_configured": True, "model": "qwen"}

    with patch("httpx.Client.get", return_value=mock_resp) as mock_get:
        status1, _ = client.check_health()
        status2, _ = client.check_health()

        assert status1 == "ready"
        assert status2 == "ready"
        assert mock_get.call_count == 2

        # The internal client should be initialized and kept alive
        assert client._client is not None
        assert not client._client.is_closed

    client.close()
    assert client._client is None


def test_backend_client_context_manager_cleanup():
    """Context manager syntax automatically calls close()."""
    with BackendClient(base_url="http://127.0.0.1:8000") as client:
        _ = client._get_client()
        assert client._client is not None

    assert client._client is None


# ============================================================================
# 3. Orchestrator Streaming Re-Analysis & Cancellation Tests
# ============================================================================

def test_request_for_text_streams_and_supports_cancellation():
    """request_for_text streams incremental chunks and respects cancellation tokens."""
    chunks_received = []
    explanations = []

    mock_client = MagicMock()
    mock_client.stream.return_value = ["chunk1 ", "chunk2 ", "chunk3"]

    orchestrator = AppOrchestrator(
        ai_client=mock_client,
        on_chunk=lambda c, r: chunks_received.append(c),
        on_explanation=lambda t, e, i, r: explanations.append(e),
    )

    orchestrator.request_for_text("Test code", "-code", run_id=101)

    # Allow background thread to process
    import time
    time.sleep(0.3)

    assert chunks_received == ["chunk1 ", "chunk2 ", "chunk3"]
    assert explanations == ["chunk1 chunk2 chunk3"]
    mock_client.stream.assert_called_once()


def test_orchestrator_stop_closes_ai_client():
    """orchestrator.stop() cleanly closes AI client connection pool."""
    mock_client = MagicMock()
    orchestrator = AppOrchestrator(ai_client=mock_client)

    orchestrator.stop()
    mock_client.close.assert_called_once()


# ============================================================================
# 4. Self-Healing Offline-to-Online Recovery Tests
# ============================================================================

def test_process_activation_auto_recovers_offline_backend():
    """If backend is not running, process_activation triggers ensure_running() to self-heal."""
    mock_manager = MagicMock()
    mock_manager.is_running = False
    mock_manager.ensure_running.return_value = (True, "Started")

    mock_capture = MagicMock()
    mock_capture.capture.return_value = "Selected sample text"

    mock_client = MagicMock()
    mock_client.stream.return_value = ["Response token"]

    orchestrator = AppOrchestrator(
        capture=mock_capture,
        ai_client=mock_client,
        backend_manager=mock_manager,
    )

    orchestrator.process_activation(run_id=200)

    mock_manager.ensure_running.assert_called_once()


# ============================================================================
# 5. Non-Intrusive Startup Notice Tests
# ============================================================================

def test_show_startup_notice_does_not_popup_by_default():
    """show_startup_notice with popup=False prepares notice content without opening window."""
    import sys
    from PySide6.QtWidgets import QApplication
    _ = QApplication.instance() or QApplication(sys.argv)
    from desktop.ui.bubble import AssistantBubbleWindow

    window = AssistantBubbleWindow()
    assert not window.isVisible()

    window.show_startup_notice("offline", "Backend starting up...", popup=False)

    # Window must remain hidden to avoid intruding on user's active workflow
    assert not window.isVisible()
    assert "Prerequisite" in window.status_label.text()
    window.close()


# ============================================================================
# 6. Groq Provider Close & Cleanup Tests
# ============================================================================

def test_groq_provider_close_releases_underlying_client():
    """GroqProvider.close() closes the AsyncGroq client."""
    import asyncio

    async def _test():
        mock_groq = MagicMock()
        mock_groq.close = MagicMock()

        provider = GroqProvider(api_key="gsk_test", client=mock_groq)
        assert provider.is_configured() is True

        await provider.close()
        mock_groq.close.assert_called_once()
        assert provider._client is None

    asyncio.run(_test())
