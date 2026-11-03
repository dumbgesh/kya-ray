"""
Unit tests for PySide6 Desktop UI:
- desktop.ui.styles
- desktop.ui.components (IntentBadge, IntentSelector, SourceTextCard, CopyButton, LoadingIndicator)
- desktop.ui.bubble (AssistantBubbleWindow)
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure repository root is on sys.path portably
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from desktop.ui.styles import LIGHT_THEME_QSS, PALETTE
from desktop.ui.components import (
    IntentBadge,
    SourceTextCard,
    CopyButton,
    LoadingIndicator,
)
from desktop.ui.bubble import AssistantBubbleWindow

# Ensure a single QApplication instance exists for all tests
app = QApplication.instance() or QApplication(sys.argv[:1])


class TestStyles(unittest.TestCase):
    def test_palette_keys(self):
        expected_keys = [
            "bg_main", "bg_card", "border", "primary", "text_primary",
            "text_secondary", "error", "success", "pill_bg", "pill_fg",
        ]
        for key in expected_keys:
            self.assertIn(key, PALETTE)

    def test_light_theme_qss_content(self):
        self.assertIn("containerFrame", LIGHT_THEME_QSS)
        self.assertIn("intentBadge", LIGHT_THEME_QSS)
        self.assertIn("responseBrowser", LIGHT_THEME_QSS)
        self.assertIn("actionButton", LIGHT_THEME_QSS)


class TestUIComponents(unittest.TestCase):
    def tearDown(self):
        app.processEvents()

    def test_intent_badge(self):
        badge = IntentBadge()
        self.assertFalse(badge.isVisible())

        badge.set_intent("-code")
        self.assertEqual(badge.text(), "Code")
        self.assertTrue(badge.isVisible())

        badge.set_intent("-explain")
        self.assertEqual(badge.text(), "Explain")
        self.assertTrue(badge.isVisible())

        badge.set_intent("unknown")
        self.assertEqual(badge.text(), "")
        self.assertFalse(badge.isVisible())

    def test_source_text_card(self):
        card = SourceTextCard()
        card.set_text("Short snippet")
        self.assertTrue(card.isVisible())
        self.assertEqual(card._text_label.text(), "Short snippet")

        # Long text should be truncated to ~160 chars
        long_text = "A" * 200
        card.set_text(long_text)
        self.assertTrue(card._text_label.text().endswith("..."))
        self.assertEqual(len(card._text_label.text()), 160)

        # Empty text hides card
        card.set_text("")
        self.assertFalse(card.isVisible())

    def test_copy_button(self):
        text_source = "Test text to copy"
        btn = CopyButton(get_text_callback=lambda: text_source)
        self.assertEqual(btn.text(), "Copy")
        self.assertEqual(btn.property("copied"), "false")

        with patch("desktop.ui.components.set_clipboard_text") as mock_set_clip:
            btn.click()
            mock_set_clip.assert_called_with("Test text to copy")
            self.assertEqual(btn.text(), "✓ Copied!")
            self.assertEqual(btn.property("copied"), "true")

            # Reset timer simulation
            btn._reset_state()
            self.assertEqual(btn.text(), "Copy")
            self.assertEqual(btn.property("copied"), "false")

    def test_loading_indicator(self):
        indicator = LoadingIndicator()
        indicator.start()
        self.assertTrue(indicator.isVisible())
        self.assertEqual(indicator.text(), "Thinking...")

        indicator._update_dots()
        self.assertEqual(indicator.text(), "Thinking.")
        indicator._update_dots()
        self.assertEqual(indicator.text(), "Thinking..")

        indicator.stop()
        self.assertFalse(indicator.isVisible())


class TestAssistantBubbleWindow(unittest.TestCase):
    def setUp(self):
        self.window = AssistantBubbleWindow()

    def tearDown(self):
        self.window.dismiss()
        self.window.deleteLater()
        app.processEvents()

    def test_window_flags_and_properties(self):
        flags = self.window.windowFlags()
        self.assertTrue(flags & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(flags & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(flags & Qt.WindowType.Tool)
        self.assertTrue(self.window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))

    def test_show_generating_state(self):
        self.window.show_generating("Explain asyncio", intent="-explain")
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.loading_indicator.isVisible())
        self.assertFalse(self.window.response_browser.isVisible())
        self.assertEqual(self.window.intent_badge.text(), "Explain")
        self.assertTrue(self.window.intent_badge.isVisible())
        self.assertFalse(self.window.copy_btn.isEnabled())

    def test_show_explanation_state(self):
        self.window.show_explanation(
            "What is Python?",
            "**Python** is an interpreted high-level language.",
            intent="-explain"
        )
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.loading_indicator.isVisible())
        self.assertTrue(self.window.response_browser.isVisible())
        self.assertIn("Python", self.window.response_browser.toPlainText())
        self.assertEqual(self.window.get_response_text(), "**Python** is an interpreted high-level language.")
        self.assertTrue(self.window.copy_btn.isEnabled())

    def test_show_error_state(self):
        self.window.show_error("import panadas", "Could not connect to Ollama")
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.loading_indicator.isVisible())
        self.assertTrue(self.window.response_browser.isVisible())
        self.assertIn("Could not connect to Ollama", self.window.response_browser.toPlainText())
        self.assertFalse(self.window.copy_btn.isEnabled())

    def test_show_no_selection_state(self):
        self.window.show_no_selection()
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window.loading_indicator.isVisible())
        self.assertIn("No text selected", self.window.response_browser.toPlainText())
        self.assertFalse(self.window.copy_btn.isEnabled())

    def test_dismiss_and_escape(self):
        dismiss_events = []
        self.window.dismissed.connect(lambda: dismiss_events.append(True))

        self.window.show()
        self.assertTrue(self.window.isVisible())

        # Test manual dismiss()
        self.window.dismiss()
        self.assertFalse(self.window.isVisible())
        self.assertEqual(dismiss_events, [True])

        # Test escape key
        self.window.show()
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        self.window.keyPressEvent(event)
        self.assertFalse(self.window.isVisible())
        self.assertEqual(len(dismiss_events), 2)

    def test_position_near_mouse(self):
        self.window.position_near_mouse(100, 150)
        pos = self.window.pos()
        self.assertEqual(pos.x(), 115)
        self.assertEqual(pos.y(), 165)

    def test_dragging_interaction(self):
        self.window.show()
        initial_pos = self.window.pos()

        # Simulate left mouse press
        from PySide6.QtGui import QMouseEvent
        press_event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPoint(10, 10),
            QPoint(100, 100),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.window.mousePressEvent(press_event)
        self.assertFalse(self.window._drag_pos.isNull())

        # Release mouse
        release_event = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPoint(10, 10),
            QPoint(100, 100),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.window.mouseReleaseEvent(release_event)
        self.assertTrue(self.window._drag_pos.isNull())


if __name__ == "__main__":
    unittest.main()
