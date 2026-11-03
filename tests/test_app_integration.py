"""
Integration and thread-safety tests for KyaRayApplication and AppSignalBridge:
- desktop.app.AppSignalBridge
- desktop.app.KyaRayApplication
"""

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

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from desktop.app import AppSignalBridge, KyaRayApplication
from desktop.core.orchestrator import AppOrchestrator
from desktop.ui.bubble import AssistantBubbleWindow

# Ensure single shared QApplication exists
app = QApplication.instance() or QApplication(sys.argv[:1])


class TestAppSignalBridge(unittest.TestCase):
    def tearDown(self):
        app.processEvents()

    def test_bridge_cross_thread_signals(self):
        """Verifies signals emitted from background worker threads reach slots safely."""
        bridge = AppSignalBridge()
        received = []

        bridge.sig_explanation.connect(
            lambda text, exp, intent, run_id: received.append((text, exp, intent, run_id))
        )

        def worker():
            bridge.sig_explanation.emit("input text", "answer text", "-explain", 10)

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # Process Qt event queue so queued connection delivers signal
        app.processEvents()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], ("input text", "answer text", "-explain", 10))


class TestKyaRayApplication(unittest.TestCase):
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

    def test_quit_on_last_window_closed_is_false(self):
        """Ensure closing the floating panel does NOT terminate background process."""
        self.assertFalse(self.app_manager.qapp.quitOnLastWindowClosed())

    def test_generating_signal_updates_window(self):
        self.app_manager._cb_generating("Selected query", "-explain", run_id=1)
        app.processEvents()

        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.loading_indicator.isVisible())
        self.assertFalse(self.window.response_browser.isVisible())

    def test_explanation_signal_updates_window(self):
        self.app_manager._cb_explanation(
            "What is DNS?",
            "Domain Name System translates domain names to IP addresses.",
            "-explain",
            run_id=2,
        )
        app.processEvents()

        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.loading_indicator.isVisible())
        self.assertTrue(self.window.response_browser.isVisible())
        self.assertIn("Domain Name System", self.window.response_browser.toPlainText())

    def test_error_signal_updates_window(self):
        self.app_manager._cb_error("Input query", "Ollama connection timed out", run_id=3)
        app.processEvents()

        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.loading_indicator.isVisible())
        self.assertIn("Ollama connection timed out", self.window.response_browser.toPlainText())

    def test_no_selection_signal_updates_window(self):
        self.app_manager._cb_no_selection(run_id=4)
        app.processEvents()

        self.assertTrue(self.window.isVisible())
        self.assertIn("No text selected", self.window.response_browser.toPlainText())

    def test_dismiss_signal_hides_window(self):
        self.window.show()
        app.processEvents()
        self.assertTrue(self.window.isVisible())

        self.app_manager._cb_dismiss()
        app.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_startup_notice_signal_updates_window(self):
        self.app_manager._cb_startup_notice("offline", "Could not connect to Ollama")
        app.processEvents()

        self.assertTrue(self.window.isVisible())
        self.assertIn("Could not connect to Ollama", self.window.response_browser.toPlainText())

    def test_shutdown_lifecycle(self):
        with patch.object(self.app_manager.qapp, "quit") as mock_quit:
            self.app_manager.shutdown()
            self.mock_orchestrator.stop.assert_called_once()
            mock_quit.assert_called_once()

            # Calling shutdown again should be idempotent
            self.app_manager.shutdown()
            self.mock_orchestrator.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
