"""
Unit tests for Kya-Ray Desktop Utilities (desktop.utils).
"""

import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from desktop.utils.config import (
    APP_NAME,
    APP_VERSION,
    OLLAMA_API_URL,
    OLLAMA_MODEL,
    REQUEST_TIMEOUT_SECONDS,
    DEFAULT_WINDOW_WIDTH,
    DEFAULT_WINDOW_HEIGHT,
    LIGHT_THEME,
    INTENT_DISPLAY_LABELS,
    get_system_theme,
    get_mouse_position,
)
from desktop.utils.logger import (
    get_log_dir,
    get_log_file_path,
    SafeOutput,
    setup_safe_logging,
)
from desktop.utils.clipboard import (
    get_clipboard_text,
    set_clipboard_text,
    preserve_clipboard,
    capture_selected_text,
)


class TestConfigUtils(unittest.TestCase):
    """Verifies configuration constants and helpers."""

    def test_app_metadata(self):
        self.assertEqual(APP_NAME, "Kya-Ray")
        self.assertTrue(bool(APP_VERSION))

    def test_ollama_settings(self):
        self.assertIn("127.0.0.1:11434", OLLAMA_API_URL)
        self.assertEqual(OLLAMA_MODEL, "llama3.2:1b")
        self.assertEqual(REQUEST_TIMEOUT_SECONDS, 30)

    def test_light_theme_palette(self):
        theme = get_system_theme()
        self.assertEqual(theme["mode"], "light")
        self.assertEqual(theme["bubble_fill"].lower(), "#ffffff")
        self.assertEqual(theme["outline"].lower(), "#e2e8f0")
        self.assertEqual(theme["text"].lower(), "#0f172a")
        self.assertEqual(theme["title"].lower(), "#0284c7")

    def test_intent_display_labels(self):
        self.assertEqual(INTENT_DISPLAY_LABELS["-explain"], "Explain")
        self.assertEqual(INTENT_DISPLAY_LABELS["-summarize"], "Summary")
        self.assertEqual(INTENT_DISPLAY_LABELS["-code"], "Code")
        self.assertEqual(INTENT_DISPLAY_LABELS["-create"], "Create")

    def test_mouse_position_query(self):
        pos = get_mouse_position()
        if pos is not None:
            self.assertIsInstance(pos, tuple)
            self.assertEqual(len(pos), 2)
            self.assertIsInstance(pos[0], int)
            self.assertIsInstance(pos[1], int)


class TestLoggerUtils(unittest.TestCase):
    """Verifies safe logging and file redirection."""

    def test_log_paths(self):
        log_dir = get_log_dir()
        self.assertTrue(os.path.isdir(log_dir))
        log_path = get_log_file_path()
        self.assertTrue(log_path.endswith("kya-ray.log"))

    def test_safe_output_stream_and_file(self):
        stream_buf = io.StringIO()
        tmp_log = os.path.join(get_log_dir(), "test_tmp.log")
        try:
            safe = SafeOutput(stream_buf, tmp_log)
            safe.write("Test message for logger\n")
            safe.flush()

            self.assertIn("Test message for logger", stream_buf.getvalue())
            self.assertTrue(os.path.isfile(tmp_log))
            with open(tmp_log, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Test message for logger", content)
        finally:
            if os.path.exists(tmp_log):
                os.remove(tmp_log)

    def test_setup_safe_logging(self):
        log_file = setup_safe_logging()
        self.assertTrue(os.path.isabs(log_file))
        self.assertTrue(hasattr(sys.stdout, "write"))
        self.assertTrue(hasattr(sys.stderr, "write"))


class TestClipboardUtils(unittest.TestCase):
    """Verifies clipboard reading, writing, preservation, and selection capture."""

    def test_clipboard_read_write(self):
        original = get_clipboard_text()
        try:
            set_clipboard_text("kya-ray-unit-test-string")
            self.assertEqual(get_clipboard_text(), "kya-ray-unit-test-string")
        finally:
            set_clipboard_text(original)

    def test_preserve_clipboard_context_manager(self):
        set_clipboard_text("original-content")
        with preserve_clipboard() as prev:
            self.assertEqual(prev, "original-content")
            set_clipboard_text("temporary-content")
            self.assertEqual(get_clipboard_text(), "temporary-content")
        self.assertEqual(get_clipboard_text(), "original-content")

    @patch("desktop.utils.clipboard.pyperclip.copy")
    @patch("desktop.utils.clipboard.pyperclip.paste")
    def test_capture_selected_text_mocked(self, mock_paste, mock_copy):
        mock_controller = MagicMock()
        # Initial clipboard -> empty clear -> captured text
        mock_paste.side_effect = ["initial-data", "highlighted snippet", "initial-data"]

        captured = capture_selected_text(controller=mock_controller)
        self.assertEqual(captured, "highlighted snippet")
        # Ensure initial data was restored
        mock_copy.assert_any_call("initial-data")


if __name__ == "__main__":
    unittest.main()

