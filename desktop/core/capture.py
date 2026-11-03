"""
desktop/core/capture.py - Selected text capture abstraction.

Coordinates text extraction from the active window using desktop.utils.clipboard.
"""

from typing import Optional
from desktop.utils.clipboard import capture_selected_text as _capture_clipboard_selection


class SelectionCapture:
    """Manages text selection capture from active external applications."""

    def __init__(self, copy_delay: float = 0.08, controller=None):
        self.copy_delay = copy_delay
        self.controller = controller

    def capture(self, timeout: float = 0.25) -> str:
        """
        Captures and returns currently highlighted text from the active window.
        Returns an empty string if no text is selected.
        """
        raw = _capture_clipboard_selection(controller=self.controller, timeout=timeout)
        return raw.strip() if raw else ""


def capture_selected_text(timeout: float = 0.25) -> str:
    """Functional convenience wrapper for text selection capture."""
    return SelectionCapture().capture(timeout=timeout)

