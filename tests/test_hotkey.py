"""
Unit tests for Kya-Ray global hotkey detection (Ctrl + Alt + Space).
Tests verify:
1. Modifier key sets: CTRL_KEYS and ALT_KEYS.
2. Space key detection across virtual key codes, pynput Key.space, and char representations.
3. Shortcut membership checks via is_shortcut_key.
4. Latching and debouncing in on_press / on_release.
"""

import sys
import unittest
from unittest.mock import patch
from pynput import keyboard

# Ensure workspace root is in path
sys.path.insert(0, "c:/kya-ray")

from prototype.main import (
    CTRL_KEYS,
    ALT_KEYS,
    is_space_key,
    is_shortcut_key,
    on_press,
    on_release,
    pressed_keys,
)
import prototype.main as main_mod


class TestHotkeyDetection(unittest.TestCase):
    """Verifies recognition and handling of Ctrl + Alt + Space."""

    def setUp(self):
        main_mod.pressed_keys.clear()
        main_mod.shortcut_triggered = False

    def tearDown(self):
        main_mod.pressed_keys.clear()
        main_mod.shortcut_triggered = False

    def test_modifier_key_sets(self):
        """Verifies both left and right Ctrl and Alt keys are included."""
        self.assertIn(keyboard.Key.ctrl, CTRL_KEYS)
        self.assertIn(keyboard.Key.ctrl_l, CTRL_KEYS)
        self.assertIn(keyboard.Key.ctrl_r, CTRL_KEYS)

        self.assertIn(keyboard.Key.alt, ALT_KEYS)
        self.assertIn(keyboard.Key.alt_l, ALT_KEYS)
        self.assertIn(keyboard.Key.alt_r, ALT_KEYS)

    def test_is_space_key_variants(self):
        """Verifies Space detection across pynput Key.space, virtual key code 32, and char ' '."""
        self.assertTrue(is_space_key(keyboard.Key.space))
        self.assertTrue(is_space_key(keyboard.KeyCode(vk=32)))
        self.assertTrue(is_space_key(keyboard.KeyCode(char=" ")))

        # Negative checks: other keys must return False
        self.assertFalse(is_space_key(keyboard.Key.enter))
        self.assertFalse(is_space_key(keyboard.Key.tab))
        self.assertFalse(is_space_key(keyboard.KeyCode(char="j")))
        self.assertFalse(is_space_key(keyboard.KeyCode(vk=74)))

    def test_is_shortcut_key(self):
        """Verifies is_shortcut_key identifies Ctrl, Alt, and Space, but no other keys."""
        for k in CTRL_KEYS:
            self.assertTrue(is_shortcut_key(k))
        for k in ALT_KEYS:
            self.assertTrue(is_shortcut_key(k))
        self.assertTrue(is_shortcut_key(keyboard.Key.space))

        # Irrelevant keys
        self.assertFalse(is_shortcut_key(keyboard.KeyCode(char="a")))
        self.assertFalse(is_shortcut_key(keyboard.KeyCode(char="z")))
        self.assertFalse(is_shortcut_key(keyboard.Key.shift))

    @patch("prototype.main.threading.Thread")
    def test_on_press_ctrl_alt_space_triggers(self, mock_thread):
        """Verifies pressing Ctrl + Alt + Space triggers the background worker thread."""
        on_press(keyboard.Key.ctrl_l)
        on_press(keyboard.Key.alt_l)
        self.assertFalse(main_mod.shortcut_triggered)
        mock_thread.assert_not_called()

        on_press(keyboard.Key.space)
        self.assertTrue(main_mod.shortcut_triggered)
        mock_thread.assert_called_once()

    @patch("prototype.main.threading.Thread")
    def test_repeat_suppression_debounce(self, mock_thread):
        """Verifies holding down Space does not re-trigger the shortcut repeatedly."""
        on_press(keyboard.Key.ctrl_l)
        on_press(keyboard.Key.alt_l)
        on_press(keyboard.Key.space)
        self.assertEqual(mock_thread.call_count, 1)

        # Repeated press while held
        on_press(keyboard.Key.space)
        self.assertEqual(mock_thread.call_count, 1)

        # Releasing space resets latch
        on_release(keyboard.Key.space)
        self.assertFalse(main_mod.shortcut_triggered)

        # Pressing again triggers new activation
        on_press(keyboard.Key.space)
        self.assertEqual(mock_thread.call_count, 2)


if __name__ == "__main__":
    unittest.main()
