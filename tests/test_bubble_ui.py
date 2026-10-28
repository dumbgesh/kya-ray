"""
Unit tests for Kya-Ray Comic Speech-Bubble UI Redesign.

Tests verify:
1. Comic speech-bubble silhouette polygon vertex calculations (bottom and top adaptive tails).
2. Backward compatibility of compute_bubble_polygon.
3. FloatingBubbleWindow widget creation, hierarchy, theme support, and legacy aliases.
4. Display state transitions (generating, explanation, error, no-selection).
5. Dynamic positioning, tail orientation adaptation, and screen clamping.
6. Window dragging calculations and hiding.
"""

import sys
import unittest
import tkinter as tk

# Ensure workspace root is in python path
sys.path.insert(0, "c:/kya-ray")

from prototype.main import (
    compute_comic_bubble_polygon,
    compute_bubble_polygon,
    get_system_theme,
    FloatingBubbleWindow,
    ResponseWindow,
)


class TestBubblePolygon(unittest.TestCase):
    """Verifies geometry and vertex generation of the comic speech-bubble silhouette."""

    def test_compute_comic_bubble_polygon_bottom_tail(self):
        w, h = 480, 270
        pts = compute_comic_bubble_polygon(w, h, r=50, tail_side="bottom", tail_tip_x=80, tail_tip_y=285)
        self.assertIsInstance(pts, list)
        self.assertEqual(len(pts) % 2, 0)
        self.assertGreater(len(pts), 40)

        xs = pts[0::2]
        ys = pts[1::2]

        # Horizontal bounds
        self.assertGreaterEqual(min(xs), 10)
        self.assertLessEqual(max(xs), w - 10)

        # Vertical bounds including bottom tail
        self.assertGreaterEqual(min(ys), 10)
        self.assertEqual(max(ys), 285)

        # Verify tail tip exists
        tail_tips = [(x, y) for x, y in zip(xs, ys) if y == 285]
        self.assertGreaterEqual(len(tail_tips), 1)
        self.assertEqual(tail_tips[0][0], 80)

    def test_compute_comic_bubble_polygon_top_tail(self):
        w, h = 480, 270
        pts = compute_comic_bubble_polygon(w, h, r=50, tail_side="top", tail_tip_x=120, tail_tip_y=5)
        self.assertIsInstance(pts, list)
        self.assertEqual(len(pts) % 2, 0)
        self.assertGreater(len(pts), 40)

        xs = pts[0::2]
        ys = pts[1::2]

        # Vertical bounds including top tail tip pointing up to y=5
        self.assertEqual(min(ys), 5)
        self.assertLessEqual(max(ys), h - 10)

        # Verify tail tip exists
        tail_tips = [(x, y) for x, y in zip(xs, ys) if y == 5]
        self.assertGreaterEqual(len(tail_tips), 1)
        self.assertEqual(tail_tips[0][0], 120)

    def test_compute_bubble_polygon_compatibility(self):
        # Test backward-compatible wrapper with legacy signature
        pts_legacy = compute_bubble_polygon(8, 8, 432, 275, r=16, tail_pos="bottom-left")
        self.assertIsInstance(pts_legacy, list)
        self.assertEqual(len(pts_legacy) % 2, 0)
        self.assertGreater(len(pts_legacy), 20)

        # Test wrapper with modern 2-arg signature
        pts_modern = compute_bubble_polygon(480, 270, r=50, tail_side="bottom", tail_tip_x=80, tail_tip_y=285)
        self.assertIsInstance(pts_modern, list)
        self.assertEqual(len(pts_modern) % 2, 0)


class TestSystemTheme(unittest.TestCase):
    """Verifies OS theme detection returns valid colors."""

    def test_theme_dict_structure(self):
        theme = get_system_theme()
        self.assertIn("mode", theme)
        self.assertIn(theme["mode"], ("light", "dark"))
        self.assertIn("bubble_fill", theme)
        self.assertIn("outline", theme)
        self.assertIn("text", theme)
        self.assertIn("trans_color", theme)
        self.assertTrue(theme["bubble_fill"].startswith("#"))
        self.assertTrue(theme["outline"].startswith("#"))


class TestFloatingBubbleWindow(unittest.TestCase):
    """Verifies FloatingBubbleWindow initialization, widgets, and state transitions."""

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        cls.app = FloatingBubbleWindow(cls.root)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def test_window_properties(self):
        self.assertEqual(self.app.width, 440)
        self.assertEqual(self.app.height, 190)
        self.assertTrue(hasattr(self.app, "canvas"))
        self.assertTrue(hasattr(self.app, "bubble_polygon"))
        self.assertTrue(hasattr(self.app, "content_frame"))
        self.assertTrue(hasattr(self.app, "header_frame"))
        self.assertTrue(hasattr(self.app, "header_status"))
        self.assertTrue(hasattr(self.app, "close_x_btn"))
        self.assertTrue(hasattr(self.app, "sel_label"))
        self.assertTrue(hasattr(self.app, "text_area"))

    def test_alias_compatibility(self):
        self.assertIs(ResponseWindow, FloatingBubbleWindow)
        self.assertIs(self.app.title_label, self.app.header_status)
        self.assertIs(self.app.footer_hint, self.app.header_status)
        self.assertIs(self.app.dismiss_btn, self.app.close_x_btn)

    def test_show_generating_state(self):
        self.app.show_generating("Sample test code snippet", intent="-code")
        status_text = self.app.header_status.cget("text")
        self.assertIn("Code", status_text)
        # Selected text must not be displayed as quoted input
        self.assertEqual(self.app.sel_label.cget("text"), "")
        content = self.app.text_area.get("1.0", tk.END)
        self.assertIn("Thinking", content)

    def test_show_explanation_state(self):
        self.app.show_explanation("Sample query", "Sample answer generated.", intent="-explain")
        status_text = self.app.header_status.cget("text")
        self.assertIn("Explain", status_text)
        # Selected text must not be displayed as quoted input
        self.assertEqual(self.app.sel_label.cget("text"), "")
        content = self.app.text_area.get("1.0", tk.END)
        self.assertIn("Sample answer generated.", content)

    def test_show_error_state(self):
        self.app.show_error("Selected query", "Connection timed out.")
        status_text = self.app.header_status.cget("text")
        self.assertIn("Error", status_text)
        content = self.app.text_area.get("1.0", tk.END)
        self.assertIn("Connection timed out.", content)

    def test_show_no_selection_state(self):
        self.app.show_no_selection()
        status_text = self.app.header_status.cget("text")
        self.assertIn("Notice", status_text)
        content = self.app.text_area.get("1.0", tk.END)
        self.assertIn("No text was selected", content)

    def test_position_bubble_adaptation(self):
        # 1. Normal positioning in middle of screen (should place above cursor with tail on bottom)
        self.app.position_bubble(500, 500)
        self.assertEqual(self.app.tail_side, "bottom")
        self.assertEqual(self.app.tail_tip_y, self.app.height - 5)

        # 2. Near top of screen (should flip below cursor with tail on top)
        self.app.position_bubble(500, 50)
        self.assertEqual(self.app.tail_side, "top")
        self.assertEqual(self.app.tail_tip_y, 5)

    def test_dragging_support(self):
        class MockEvent:
            def __init__(self, x_root, y_root):
                self.x_root = x_root
                self.y_root = y_root

        self.app._on_drag_start(MockEvent(100, 100))
        self.assertEqual(self.app._drag_start_x, 100)
        self.assertEqual(self.app._drag_start_y, 100)

    def test_hide_window(self):
        self.app.hide_window()
        self.assertEqual(self.root.state(), "withdrawn")

    def test_copy_button_present_and_copies(self):
        """Verifies Copy button is present and copies answer to clipboard with transient feedback."""
        self.assertTrue(hasattr(self.app, "copy_btn"))
        self.assertEqual(self.app.copy_btn.cget("text"), "Copy")
        self.app._current_raw_answer = "Test answer text to copy"
        self.app.on_copy()
        self.assertEqual(self.app.copy_btn.cget("text"), "Copied!")
        import pyperclip
        self.assertEqual(pyperclip.paste(), "Test answer text to copy")

    def test_render_formatted_response_tags(self):
        """Verifies render_formatted_response populates text and sets appropriate tags."""
        try:
            from prototype.main import render_formatted_response
        except ImportError:
            self.fail("render_formatted_response must be defined in prototype.main")

        text_widget = tk.Text(self.root)
        sample = (
            "Here is an explanation paragraph.\n\n"
            "- Point one\n"
            "- Point two\n\n"
            "```python\napp = FastAPI()\n```"
        )
        render_formatted_response(text_widget, sample)
        content = text_widget.get("1.0", tk.END)
        self.assertIn("Here is an explanation paragraph.", content)
        self.assertIn("Point one", content)
        self.assertIn("app = FastAPI()", content)

    def test_dynamic_window_sizing(self):
        """Verifies window adjusts height dynamically between compact and max limits."""
        # Short explanation should keep window compact
        self.app.show_explanation("query", "Short one sentence answer.")
        self.assertLessEqual(self.app.height, 220)

        # Long explanation should expand up to max height
        long_text = "\n".join(f"Paragraph line {i} explaining a complex topic." for i in range(12))
        self.app.show_explanation("query", long_text)
        self.assertGreaterEqual(self.app.height, 260)
        self.assertLessEqual(self.app.height, 360)


if __name__ == "__main__":
    unittest.main()
