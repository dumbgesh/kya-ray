"""
Unit and integration tests for Kya-Ray Desktop BackendClient, Streaming UI, and Cancellation:
- desktop.ai.backend_client.BackendClient
- desktop.ui.bubble streaming methods (append_stream_chunk, finish_stream)
- desktop.core.orchestrator streaming and cancellation
- desktop.app streaming signal bridge integration
"""

import io
import json
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure repository root is on sys.path portably
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import httpx
from PySide6.QtWidgets import QApplication

from desktop.ai.backend_client import BackendClient, BackendResponse
from desktop.app import KyaRayApplication
from desktop.core.orchestrator import AppOrchestrator
from desktop.ui.bubble import AssistantBubbleWindow

app = QApplication.instance() or QApplication(sys.argv[:1])


class TestBackendClient(unittest.TestCase):
    def test_backend_response_repr(self):
        resp = BackendResponse(True, "Response text", "-explain", "mock-model")
        self.assertTrue(resp.success)
        self.assertEqual(resp.content, "Response text")
        self.assertEqual(resp.intent, "-explain")
        self.assertIn("BackendResponse", repr(resp))

    @patch("httpx.Client.get")
    def test_check_health_ready(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"groq_configured": True, "model": "llama-3.3-70b-versatile"}
        mock_get.return_value = mock_resp

        client = BackendClient(base_url="http://127.0.0.1:8000")
        status, msg = client.check_health()
        self.assertEqual(status, "ready")
        self.assertIn("running with llama-3.3-70b-versatile", msg)

    @patch("httpx.Client.get")
    def test_check_health_groq_missing(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"groq_configured": False, "model": "llama-3.3-70b-versatile"}
        mock_get.return_value = mock_resp

        client = BackendClient(base_url="http://127.0.0.1:8000")
        status, msg = client.check_health()
        self.assertEqual(status, "groq_unconfigured")
        self.assertIn("GROQ_API_KEY is not configured", msg)

    @patch("httpx.Client.get")
    def test_check_health_offline(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        client = BackendClient(base_url="http://127.0.0.1:8000")
        status, msg = client.check_health()
        self.assertEqual(status, "offline")
        self.assertIn("Could not connect", msg)

    @patch("httpx.Client.post")
    def test_generate_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "content": "Python is dynamic.",
            "intent": "-explain",
            "model": "llama-3.3-70b-versatile",
            "usage": {"total_tokens": 15},
        }
        mock_post.return_value = mock_resp

        client = BackendClient(base_url="http://127.0.0.1:8000")
        resp = client.generate("Python", intent="-explain")
        self.assertTrue(resp.success)
        self.assertEqual(resp.content, "Python is dynamic.")
        self.assertEqual(resp.intent, "-explain")

    @patch("httpx.Client.post")
    def test_generate_auth_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"detail": "Invalid Groq API Key"}
        mock_post.return_value = mock_resp

        client = BackendClient()
        resp = client.generate("Hello")
        self.assertFalse(resp.success)
        self.assertIn("authentication error", resp.content)

    @patch("httpx.Client.post")
    def test_generate_rate_limit(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_post.return_value = mock_resp

        client = BackendClient()
        resp = client.generate("Hello")
        self.assertFalse(resp.success)
        self.assertIn("rate limit exceeded", resp.content.lower())

    @patch("httpx.Client.post")
    def test_generate_connection_error(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("Failed to reach server")

        client = BackendClient(base_url="http://127.0.0.1:8000")
        resp = client.generate("Hello")
        self.assertFalse(resp.success)
        self.assertIn("Could not connect", resp.content)

    def test_stream_chunks_and_done(self):
        client = BackendClient(base_url="http://127.0.0.1:8000")

        # Mock streaming response
        sse_lines = [
            'data: {"chunk": "Hello "}\n',
            'data: {"chunk": "streaming "}\n',
            'data: {"chunk": "world!"}\n',
            'data: [DONE]\n',
        ]

        class MockStreamContext:
            def __init__(self, lines):
                self.lines = lines
                self.status_code = 200
                self.reason_phrase = "OK"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def iter_lines(self):
                for line in self.lines:
                    yield line

        with patch("httpx.Client.stream", return_value=MockStreamContext(sse_lines)):
            tokens = list(client.stream("Prompt", "-explain"))
            self.assertEqual("".join(tokens), "Hello streaming world!")

    def test_stream_cancellation(self):
        client = BackendClient()
        cancel_event = threading.Event()

        # Simulate 10 chunks, but cancel after 2nd
        sse_lines = [
            'data: {"chunk": "One"}\n',
            'data: {"chunk": "Two"}\n',
            'data: {"chunk": "Three"}\n',
            'data: {"chunk": "Four"}\n',
        ]

        class MockStreamContext:
            def __init__(self, lines):
                self.lines = lines
                self.status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def iter_lines(self):
                for line in self.lines:
                    yield line

        collected = []
        with patch("httpx.Client.stream", return_value=MockStreamContext(sse_lines)):
            for token in client.stream("Test", cancel_event=cancel_event):
                collected.append(token)
                if len(collected) == 2:
                    cancel_event.set()

        # Should have stopped after cancellation
        self.assertEqual(len(collected), 2)
        self.assertEqual(collected, ["One", "Two"])


class TestAssistantBubbleWindowStreaming(unittest.TestCase):
    def setUp(self):
        self.window = AssistantBubbleWindow()

    def tearDown(self):
        self.window.dismiss()
        self.window.deleteLater()
        app.processEvents()

    def test_streaming_lifecycle(self):
        # 1. Start thinking
        self.window.show_generating("Input snippet", intent="-code")
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.loading_indicator.isVisible())
        self.assertFalse(self.window.response_browser.isVisible())
        self.assertEqual(self.window.intent_badge.text(), "Code")

        # 2. First chunk arrives
        self.window.append_stream_chunk("First token ")
        self.assertFalse(self.window.loading_indicator.isVisible())
        self.assertTrue(self.window.response_browser.isVisible())
        self.assertIn("First token", self.window.response_browser.toPlainText())

        # 3. Successive chunks
        self.window.append_stream_chunk("second token.")
        self.assertIn("First token second token.", self.window.response_browser.toPlainText())

        # 4. Stream finished
        self.window.finish_stream(intent="-code")
        self.assertTrue(self.window.copy_btn.isEnabled())
        self.assertEqual(self.window.get_response_text(), "First token second token.")


class TestAppOrchestratorStreamingAndCancellation(unittest.TestCase):
    def test_orchestrator_streaming_pipeline(self):
        mock_capture = MagicMock()
        mock_capture.capture.return_value = "git status"

        mock_backend = MagicMock(spec=BackendClient)
        mock_backend.stream.return_value = iter(["Branch ", "is ", "clean."])

        chunks = []
        explanation_events = []
        generating_events = []

        orchestrator = AppOrchestrator(
            ai_client=mock_backend,
            capture=mock_capture,
            on_generating=lambda text, intent, run_id: generating_events.append((text, intent, run_id)),
            on_chunk=lambda chunk, run_id: chunks.append(chunk),
            on_explanation=lambda text, exp, intent, run_id: explanation_events.append((text, exp, intent, run_id)),
        )

        orchestrator.process_activation(run_id=1)

        self.assertEqual(len(generating_events), 1)
        self.assertEqual(generating_events[0][1], "-code")  # Auto-detected intent
        self.assertEqual(chunks, ["Branch ", "is ", "clean."])
        self.assertEqual(len(explanation_events), 1)
        self.assertEqual(explanation_events[0][1], "Branch is clean.")
        self.assertEqual(explanation_events[0][2], "-code")

    def test_orchestrator_stream_cancellation(self):
        mock_capture = MagicMock()
        mock_capture.capture.return_value = "Long text"

        cancel_event = threading.Event()
        cancel_event.set()  # Cancelled before start

        mock_backend = MagicMock(spec=BackendClient)

        generating_events = []
        orchestrator = AppOrchestrator(
            ai_client=mock_backend,
            capture=mock_capture,
            on_generating=lambda *args: generating_events.append(args),
        )

        orchestrator.process_activation(run_id=5, cancel_event=cancel_event)

        # Should abort immediately
        self.assertEqual(len(generating_events), 0)
        mock_backend.stream.assert_not_called()

    def test_dismiss_triggers_active_cancellation(self):
        orchestrator = AppOrchestrator()
        orchestrator._active_cancel_event = threading.Event()
        self.assertFalse(orchestrator._active_cancel_event.is_set())

        orchestrator._handle_hotkey_dismiss()
        self.assertTrue(orchestrator._active_cancel_event.is_set())


class TestKyaRayApplicationStreaming(unittest.TestCase):
    def setUp(self):
        self.mock_orchestrator = MagicMock(spec=AppOrchestrator)
        self.window = AssistantBubbleWindow()
        self.app_manager = KyaRayApplication(
            qapp=app,
            orchestrator=self.mock_orchestrator,
            window=self.window,
        )

    def tearDown(self):
        self.app_manager.shutdown()
        self.window.deleteLater()
        app.processEvents()

    def test_chunk_signal_streams_to_window(self):
        self.window.show_generating("Query", intent="-explain")
        app.processEvents()
        self.assertTrue(self.window.loading_indicator.isVisible())

        # Stream chunk
        self.app_manager._cb_chunk("Hello streamed world", run_id=1)
        app.processEvents()

        self.assertFalse(self.window.loading_indicator.isVisible())
        self.assertTrue(self.window.response_browser.isVisible())
        self.assertIn("Hello streamed world", self.window.response_browser.toPlainText())


if __name__ == "__main__":
    unittest.main()

