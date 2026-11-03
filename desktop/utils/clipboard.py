"""
Clipboard Management and Context Capture Helpers for Kya-Ray Desktop.
"""

from contextlib import contextmanager
import time
import pyperclip
from pynput import keyboard


_fallback_clipboard = ""


def get_clipboard_text():
    """Reads current text from system clipboard safely with retry and fallback."""
    for _ in range(3):
        try:
            return pyperclip.paste()
        except Exception:
            time.sleep(0.03)
    return _fallback_clipboard


def set_clipboard_text(text):
    """Writes text to system clipboard safely with retry and fallback."""
    global _fallback_clipboard
    _fallback_clipboard = str(text) if text is not None else ""
    for _ in range(3):
        try:
            pyperclip.copy(text)
            return
        except Exception:
            time.sleep(0.03)


@contextmanager
def preserve_clipboard():
    """
    Context manager that records existing clipboard contents on entry
    and guarantees restoration on exit.
    """
    previous = get_clipboard_text()
    try:
        yield previous
    finally:
        set_clipboard_text(previous)


def has_clipboard_text() -> bool:
    """Checks whether Unicode text format is available on system clipboard without mutating it."""
    try:
        import ctypes
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "user32"):
            # CF_UNICODETEXT = 13
            return bool(ctypes.windll.user32.IsClipboardFormatAvailable(13))
    except Exception:
        pass
    return True


def get_clipboard_sequence() -> int:
    """Returns the Windows clipboard sequence number to detect clipboard mutations without destructive clearing."""
    try:
        import ctypes
        if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "user32"):
            return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:
        pass
    return -1


def capture_selected_text(controller=None, timeout=0.25):
    """
    Captures currently selected text from whichever application is active.
    Uses an adaptive temporary clipboard approach:
    1. Saves the user's current clipboard content.
    2. Clears the clipboard to detect if new text is actually copied.
    3. Releases active Alt, Shift, and Ctrl keys cleanly.
    4. Simulates clean Ctrl + C to copy the active selection.
    5. Polls with timeout until text is copied.
    6. Restores the user's original clipboard content.
    """
    if controller is None:
        controller = keyboard.Controller()

    previous_clipboard = get_clipboard_text()
    selected_text = ""

    try:
        set_clipboard_text("")
        time.sleep(0.015)

        # Temporarily release active modifier keys so active application registers clean 'Ctrl + C'
        controller.release(keyboard.Key.alt)
        controller.release(keyboard.Key.alt_l)
        controller.release(keyboard.Key.alt_r)
        if hasattr(keyboard.Key, "alt_gr"):
            controller.release(keyboard.Key.alt_gr)
        controller.release(keyboard.Key.shift)
        controller.release(keyboard.Key.shift_l)
        controller.release(keyboard.Key.shift_r)
        controller.release(keyboard.Key.ctrl)
        controller.release(keyboard.Key.ctrl_l)
        controller.release(keyboard.Key.ctrl_r)

        time.sleep(0.015)

        # Simulate clean Ctrl + C to copy the highlighted text
        controller.press(keyboard.Key.ctrl)
        time.sleep(0.01)
        controller.tap("c")
        time.sleep(0.01)
        controller.release(keyboard.Key.ctrl)

        # Poll with timeout until text arrives from active application
        poll_start = time.perf_counter()
        while (time.perf_counter() - poll_start) < timeout:
            time.sleep(0.02)
            selected_text = get_clipboard_text()
            if selected_text:
                break

    except Exception as error:
        print(f"[Warning] Error during text capture: {error}", flush=True)

    finally:
        # Guarantee restoration of previous clipboard content
        if previous_clipboard:
            set_clipboard_text(previous_clipboard)
        elif selected_text:
            set_clipboard_text("")

    return selected_text

