"""
tests/test_step10_reliability.py - Regression test suite for Step 10 Reliability & Real-World Testing.
"""

import unittest
from PySide6.QtWidgets import QApplication
from desktop.ui.bubble import AssistantBubbleWindow
from desktop.app import KyaRayApplication
from desktop.core.orchestrator import AppOrchestrator
from desktop.core.hotkey import HotkeyListener

# Initialize QApplication once for Qt widget tests
qapp = QApplication.instance() or QApplication([])


class TestRunIDProtection(unittest.TestCase):
    """
    Step 10 Fix 1: Run ID Protection.
    Verifies that chunks and responses from stale/superseded run_ids
    are rejected and never interleave into the active response.
    """

    def setUp(self):
        self.window = AssistantBubbleWindow()

    def tearDown(self):
        self.window.dismiss()
        self.window.close()

    def test_stale_chunks_rejected_after_new_run_started(self):
        """When run_id 2 starts, trailing chunks from run_id 1 must be discarded."""
        # Run 1 starts
        self.window.show_generating("First text", "-explain", run_id=1)
        self.window.append_stream_chunk("Chunk 1A", run_id=1)
        self.assertEqual(self.window.get_response_text(), "Chunk 1A")

        # Run 2 starts (cancelling or superseding Run 1)
        self.window.show_generating("Second text", "-code", run_id=2)
        self.assertEqual(self.window.get_response_text(), "")

        # Stale chunk arrives from Run 1
        self.window.append_stream_chunk("Chunk 1B", run_id=1)
        # Verify stale chunk was dropped
        self.assertEqual(self.window.get_response_text(), "")

        # Valid chunk arrives from Run 2
        self.window.append_stream_chunk("Chunk 2A", run_id=2)
        self.assertEqual(self.window.get_response_text(), "Chunk 2A")

    def test_stale_explanation_rejected(self):
        """When run_id 2 is active, a completion signal from run_id 1 must be ignored."""
        self.window.show_generating("Second text", "-code", run_id=2)
        self.window.append_stream_chunk("Valid 2", run_id=2)

        # Stale explanation completion arrives from Run 1
        self.window.show_explanation("First text", "Stale explanation 1", "-explain", run_id=1)
        # Content remains from Run 2
        self.assertEqual(self.window.get_response_text(), "Valid 2")

    def test_stale_error_rejected(self):
        """When run_id 2 is active, an error signal from run_id 1 must be ignored."""
        self.window.show_generating("Second text", "-code", run_id=2)
        self.window.append_stream_chunk("Active progress", run_id=2)

        # Stale error arrives from Run 1
        self.window.show_error("First text", "Connection dropped in run 1", run_id=1)
        # Content remains active progress from Run 2
        self.assertEqual(self.window.get_response_text(), "Active progress")


class TestStreamErrorHandling(unittest.TestCase):
    """
    Step 10 Fix 2: Mid-Stream Error Handling.
    Verifies that mid-stream network drops and error chunks are explicitly detected,
    never passed as valid text, and always routed to on_error rather than on_explanation.
    """

    def test_mid_stream_failure_routes_to_error_not_explanation(self):
        """
        When streaming fails after partial chunks (e.g. connection dropped),
        the error chunk must not be appended as valid response, and on_error
        must be called instead of on_explanation.
        """
        class MockStreamingClient:
            def stream(self, text, intent=None, cancel_event=None):
                yield "Valid chunk 1. "
                yield "Valid chunk 2. "
                # Mid-stream connection reset error
                yield "Error during streaming: Connection reset by peer"

        class MockCapture:
            def capture(self):
                return "def foo(): pass"

        chunks_received = []
        errors_received = []
        explanations_received = []

        orchestrator = AppOrchestrator(
            ai_client=MockStreamingClient(),
            capture=MockCapture(),
            on_chunk=lambda chunk, rid: chunks_received.append(chunk),
            on_explanation=lambda t, exp, i, rid: explanations_received.append(exp),
            on_error=lambda t, err, rid: errors_received.append(err),
        )

        orchestrator.process_activation(run_id=42)

        # Verified: Only the valid chunks were passed to on_chunk
        self.assertEqual(chunks_received, ["Valid chunk 1. ", "Valid chunk 2. "])
        # Verified: The error chunk was NOT appended into on_chunk
        self.assertNotIn("Error during streaming: Connection reset by peer", chunks_received)

        # Verified: on_error was called with the failure description
        self.assertEqual(len(errors_received), 1)
        self.assertIn("Connection reset by peer", errors_received[0])

        # Verified: on_explanation was NEVER called
        self.assertEqual(len(explanations_received), 0)

    def test_sse_error_payload_routes_to_on_error(self):
        """When backend yields an SSE error frame [Error: ...], on_error must be triggered."""
        class MockErrorStreamClient:
            def stream(self, text, intent=None, cancel_event=None):
                yield "\n\n[Error: Rate limit exceeded]"

        class MockCapture:
            def capture(self):
                return "DNS"

        errors_received = []
        explanations_received = []

        orchestrator = AppOrchestrator(
            ai_client=MockErrorStreamClient(),
            capture=MockCapture(),
            on_chunk=lambda chunk, rid: None,
            on_explanation=lambda t, exp, i, rid: explanations_received.append(exp),
            on_error=lambda t, err, rid: errors_received.append(err),
        )

        orchestrator.process_activation(run_id=99)

        self.assertEqual(len(errors_received), 1)
        self.assertIn("Rate limit exceeded", errors_received[0])
        self.assertEqual(len(explanations_received), 0)


class TestHotkeyReliability(unittest.TestCase):
    """
    Step 10 Fix 3: Hotkey Reliability.
    Verifies that:
    1. Legitimate Ctrl + Alt + Space activations work and latch properly.
    2. Stuck modifier states from dropped OS release events are purged.
    3. Esc and reset() clear all active key tracking.
    """

    def test_hotkey_repeated_activations(self):
        """Sequential Ctrl + Alt + Space triggers must increment run_counter."""
        triggers = []
        listener = HotkeyListener(on_trigger=lambda rid: triggers.append(rid))

        from pynput import keyboard

        # Press Ctrl + Alt + Space
        listener._on_press(keyboard.Key.ctrl_l)
        listener._on_press(keyboard.Key.alt_l)
        listener._on_press(keyboard.Key.space)
        self.assertEqual(triggers, [1])

        # Release Space, press Space again (still holding Ctrl + Alt)
        listener._on_release(keyboard.Key.space)
        listener._on_press(keyboard.Key.space)
        self.assertEqual(triggers, [1, 2])

        # Full release
        listener._on_release(keyboard.Key.ctrl_l)
        listener._on_release(keyboard.Key.alt_l)
        listener._on_release(keyboard.Key.space)
        self.assertEqual(len(listener.pressed_keys), 0)

    def test_stuck_modifiers_purged_on_isolated_space_press(self):
        """If modifiers were left in pressed_keys but physically released, pressing Space must not trigger."""
        from unittest.mock import MagicMock
        triggers = []
        listener = HotkeyListener(on_trigger=lambda rid: triggers.append(rid))
        # Simulate active live listener
        listener._listener = MagicMock(is_alive=lambda: True)

        from pynput import keyboard

        # Simulate orphaned modifier keys stuck in set (e.g. from lost OS release event)
        listener.pressed_keys.add(keyboard.Key.ctrl_l)
        listener.pressed_keys.add(keyboard.Key.alt_l)

        # On non-interactive test runner, GetAsyncKeyState returns False for Ctrl/Alt
        # User subsequently presses Space alone while typing in another app
        listener._on_press(keyboard.Key.space)

        # Verified: Hotkey did NOT trigger because physical modifier state was not down
        self.assertEqual(triggers, [])
        # Verified: Orphaned modifier keys were cleaned up from tracking
        self.assertNotIn(keyboard.Key.ctrl_l, listener.pressed_keys)
        self.assertNotIn(keyboard.Key.alt_l, listener.pressed_keys)

    def test_esc_resets_hotkey_state(self):
        """Pressing Esc must reset all pressed keys and unlatch shortcut state."""
        dismissals = []
        listener = HotkeyListener(on_dismiss=lambda: dismissals.append(True))
        from pynput import keyboard

        listener.pressed_keys.add(keyboard.Key.ctrl_l)
        listener.pressed_keys.add(keyboard.Key.alt_l)
        listener.shortcut_triggered = True

        listener._on_release(keyboard.Key.esc)

        self.assertEqual(len(dismissals), 1)
        self.assertEqual(len(listener.pressed_keys), 0)
        self.assertFalse(listener.shortcut_triggered)


class TestClipboardReliability(unittest.TestCase):
    """
    Step 10 Fix 4: Clipboard Capture and Preservation.
    Verifies that:
    1. User's pre-existing clipboard text is preserved after selection capture.
    2. Polling loop catches delayed clipboard responses from slow applications.
    3. Modifier keys (Alt, Shift, Ctrl) are cleanly released before Ctrl+C simulation.
    """

    def test_original_clipboard_preserved_after_capture(self):
        """User's pre-existing clipboard contents must remain untouched after capture."""
        from desktop.utils.clipboard import get_clipboard_text, set_clipboard_text, capture_selected_text
        from unittest.mock import MagicMock

        # Set user's clipboard to valuable work data
        set_clipboard_text("user-important-clipboard-content")
        mock_controller = MagicMock()

        # Execute capture
        captured = capture_selected_text(controller=mock_controller, timeout=0.05)

        # After capture finishes, the original clipboard content must be intact
        self.assertEqual(get_clipboard_text(), "user-important-clipboard-content")

    def test_delayed_copy_captured_by_polling(self):
        """If application takes 40ms to write to clipboard, polling must capture it."""
        from desktop.utils.clipboard import capture_selected_text
        from unittest.mock import MagicMock, patch

        mock_controller = MagicMock()

        # Sequence:
        # 1. get_clipboard_text() (save original) -> 'user-orig'
        # 2. get_clipboard_text() (first poll) -> '' (app is slow)
        # 3. get_clipboard_text() (second poll) -> 'newly-highlighted-text'
        # 4. finally restore
        with patch("desktop.utils.clipboard.get_clipboard_text") as mock_get:
            mock_get.side_effect = [
                "user-orig",
                "",
                "newly-highlighted-text",
                "user-orig",
            ]
            captured = capture_selected_text(controller=mock_controller, timeout=0.15)
            self.assertEqual(captured, "newly-highlighted-text")

    def test_clean_modifier_releases_before_ctrl_c(self):
        """All modifier variants must be explicitly released before tapping 'c'."""
        from desktop.utils.clipboard import capture_selected_text
        from unittest.mock import MagicMock
        from pynput import keyboard

        mock_controller = MagicMock()
        capture_selected_text(controller=mock_controller, timeout=0.04)

        # Check that Alt, Shift, and Ctrl release calls were made
        released_keys = [call.args[0] for call in mock_controller.release.call_args_list]
        self.assertIn(keyboard.Key.alt, released_keys)
        self.assertIn(keyboard.Key.shift, released_keys)
        self.assertIn(keyboard.Key.ctrl, released_keys)


if __name__ == "__main__":
    unittest.main()
