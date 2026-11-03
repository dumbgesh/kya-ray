"""
desktop/core/hotkey.py - Global hotkey listener and debouncing.

Manages low-level keyboard hook via pynput to detect Ctrl + Alt + Space and Esc.
Ensures single-fire debouncing (latch pattern) and clean background thread triggers.
"""

import sys
from typing import Any, Callable, Optional, Set
from pynput import keyboard

CTRL_KEYS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
ALT_KEYS = {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}
if hasattr(keyboard.Key, "alt_gr"):
    ALT_KEYS.add(keyboard.Key.alt_gr)
SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}


def is_key_physically_held(vk: int) -> bool:
    """Checks whether a virtual key is physically pressed down on Windows."""
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return True


def is_space_key(key) -> bool:
    """
    Checks if a key event represents the Space key.
    Handles pynput Key.space, character ' ', and Windows virtual key code (VK_SPACE = 32).
    """
    if key == keyboard.Key.space:
        return True
    if isinstance(key, keyboard.KeyCode):
        if getattr(key, "vk", None) == 32:
            return True
        if key.char == " ":
            return True
    return False


def is_shortcut_key(key) -> bool:
    """Check if the given key is part of our shortcut combination (Ctrl + Alt + Space)."""
    if key in CTRL_KEYS or key in ALT_KEYS:
        return True
    if is_space_key(key):
        return True
    return False


def is_j_key(key) -> bool:
    """Deprecated alias preserved for backward compatibility."""
    return is_space_key(key)


class HotkeyListener:
    """
    Listens for global shortcut activation (Ctrl + Alt + Space) and panel dismissal (Esc).
    Dispatches callbacks when combinations are satisfied.
    """

    def __init__(
        self,
        on_trigger: Optional[Callable[[int], None]] = None,
        on_dismiss: Optional[Callable[[], None]] = None,
    ):
        self.on_trigger = on_trigger
        self.on_dismiss = on_dismiss
        self.pressed_keys: Set[Any] = set()
        self.shortcut_triggered = False
        self.run_counter = 0
        self._listener: Optional[keyboard.Listener] = None

    def reset(self):
        """Safely resets tracked keys and trigger latch."""
        self.pressed_keys.clear()
        self.shortcut_triggered = False

    def purge_stale_modifiers(self):
        """Actively purges orphaned modifier keys that are no longer physically held down on Windows."""
        if sys.platform == "win32":
            if not is_key_physically_held(0x11):  # VK_CONTROL
                self.pressed_keys.difference_update(CTRL_KEYS)
            if not is_key_physically_held(0x12):  # VK_MENU (Alt)
                self.pressed_keys.difference_update(ALT_KEYS)

    def _on_press(self, key):
        self.pressed_keys.add(key)

        # In live listening sessions, actively purge orphaned modifier keys if they are no longer physically held
        if self._listener is not None and getattr(self._listener, "is_alive", lambda: False)():
            self.purge_stale_modifiers()

        ctrl_held = any(k in self.pressed_keys for k in CTRL_KEYS)
        alt_held = any(k in self.pressed_keys for k in ALT_KEYS)
        space_pressed_now = is_space_key(key)

        if ctrl_held and alt_held and space_pressed_now:
            if not self.shortcut_triggered:
                self.shortcut_triggered = True
                self.run_counter += 1
                run_id = self.run_counter
                if self.on_trigger:
                    self.on_trigger(run_id)

    def _on_release(self, key):
        self.pressed_keys.discard(key)

        if is_shortcut_key(key):
            self.shortcut_triggered = False

        if key == keyboard.Key.esc:
            self.reset()
            if self.on_dismiss:
                self.on_dismiss()

    def start(self):
        """Starts the keyboard listener in a background thread."""
        if self._listener is None or not self._listener.is_alive():
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.start()

    def stop(self):
        """Stops the keyboard listener."""
        if self._listener and self._listener.is_alive():
            self._listener.stop()
            self._listener = None

    def is_alive(self) -> bool:
        """Returns True if the listener thread is active."""
        return self._listener is not None and self._listener.is_alive()
