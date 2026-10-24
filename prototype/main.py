import threading
import time
import pyperclip
from pynput import keyboard

# Sets of modifier keys to track (supports both left and right keys)
CTRL_KEYS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}

# State variables
pressed_keys = set()
shortcut_triggered = False

# Controller used to simulate keyboard events (e.g. Ctrl + C)
keyboard_controller = keyboard.Controller()


def is_j_key(key):
    """
    Check if a key event represents the letter 'J'.
    On Windows, when Ctrl is held down, pynput often translates 'J'
    into a control character ('\n', ASCII 10) instead of 'j'.
    We check both the virtual key code (vk=74) and character representations.
    """
    if isinstance(key, keyboard.KeyCode):
        # 74 is the Windows virtual key code for 'J' (ord('J'))
        if getattr(key, "vk", None) == ord("J"):
            return True
        if key.char is not None and key.char.lower() in ("j", "\n"):
            return True
    return False


def is_shortcut_key(key):
    """Check if the given key is part of our shortcut combination."""
    if key in CTRL_KEYS or key in SHIFT_KEYS:
        return True
    if is_j_key(key):
        return True
    return False


def capture_selected_text():
    """
    Captures currently selected text from whichever application is active.
    Uses a temporary clipboard approach:
    1. Saves the user's current clipboard content.
    2. Clears the clipboard to detect if new text is actually copied.
    3. Simulates Ctrl + C to copy the active selection.
    4. Reads the newly copied text.
    5. Restores the user's original clipboard content.
    """
    # Step 1: Save existing clipboard content
    try:
        previous_clipboard = pyperclip.paste()
    except Exception:
        previous_clipboard = ""

    selected_text = ""
    try:
        # Step 2: Clear clipboard so previous data is not mistaken for a new selection
        pyperclip.copy("")
        time.sleep(0.02)

        # Step 3: Temporarily release Shift so the app sees 'Ctrl + C'
        # instead of 'Ctrl + Shift + C' (which opens developer tools in some apps)
        keyboard_controller.release(keyboard.Key.shift)
        keyboard_controller.release(keyboard.Key.shift_l)
        keyboard_controller.release(keyboard.Key.shift_r)

        # Step 4: Simulate pressing Ctrl + C to copy the highlighted text
        with keyboard_controller.pressed(keyboard.Key.ctrl):
            keyboard_controller.tap("c")

        # Step 5: Brief pause to allow the active window to complete the copy operation
        time.sleep(0.08)

        # Step 6: Read whatever was copied into the clipboard
        selected_text = pyperclip.paste()

    except Exception as error:
        print(f"[Warning] Error during text capture: {error}", flush=True)

    finally:
        # Step 7: Restore the user's original clipboard content
        try:
            pyperclip.copy(previous_clipboard)
        except Exception:
            pass

    return selected_text


def process_shortcut_event():
    """
    Runs in a background thread when the shortcut is triggered.
    Captures the selected text and displays the result without blocking the keyboard listener.
    """
    print("\n--- Shortcut detected: Ctrl + Shift + J ---", flush=True)
    captured_text = capture_selected_text()

    if captured_text and captured_text.strip():
        print("Captured text:", flush=True)
        print(captured_text, flush=True)
        print("------------------------------------------\n", flush=True)
    else:
        print("[No text selected]\n", flush=True)


def on_press(key):
    """
    Called whenever any key is pressed down.
    Adds key to pressed_keys and checks if the shortcut was just completed.
    """
    global shortcut_triggered

    pressed_keys.add(key)

    # Check if any Ctrl and any Shift are currently being held
    ctrl_held = any(k in pressed_keys for k in CTRL_KEYS)
    shift_held = any(k in pressed_keys for k in SHIFT_KEYS)

    # Check if the key pressed *right now* is 'J'
    j_pressed_now = is_j_key(key)

    if ctrl_held and shift_held and j_pressed_now:
        # Latch: fire only once per key combination press
        if not shortcut_triggered:
            shortcut_triggered = True

            # Run capture in a daemon thread so the keyboard hook returns immediately
            # without stuttering or delaying the user's keyboard input.
            threading.Thread(target=process_shortcut_event, daemon=True).start()


def on_release(key):
    """
    Called whenever any key is released.
    Removes key from pressed_keys and resets the trigger latch when needed.
    """
    global shortcut_triggered

    pressed_keys.discard(key)

    # If any key involved in the shortcut is released, reset the latch
    if is_shortcut_key(key):
        shortcut_triggered = False

    # Pressing Esc stops the listener cleanly by returning False
    if key == keyboard.Key.esc:
        print("\nEsc pressed. Exiting...", flush=True)
        return False


def main():
    print("=" * 50, flush=True)
    print("Kya-Ray - Version 2: Selected Text Capture", flush=True)
    print("=" * 50, flush=True)
    print("Instructions:", flush=True)
    print("  * Select text in any window and press Ctrl + Shift + J.", flush=True)
    print("  * If no text is selected, it will report [No text selected].", flush=True)
    print("  * Your previous clipboard content is preserved.", flush=True)
    print("  * Press Esc to exit.", flush=True)
    print("=" * 50 + "\n", flush=True)

    try:
        with keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
        ) as listener:
            listener.join()
    except Exception as error:
        print(f"\n[Error] Failed to start keyboard listener: {error}", flush=True)
        print("Please ensure your terminal has appropriate permissions to monitor keyboard input.", flush=True)
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...", flush=True)


if __name__ == "__main__":
    main()