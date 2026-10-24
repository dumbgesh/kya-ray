from pynput import keyboard

# Sets of modifier keys to track (supports both left and right keys)
CTRL_KEYS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}

# State variables
pressed_keys = set()
shortcut_triggered = False


def is_j_key(key):
    """
    Check if a key event represents the letter 'J'.
    On Windows, when Ctrl is held down, pynput often translates 'J'
    into a control character ('\\n', ASCII 10) instead of 'j'.
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
    # This ensures the shortcut triggers only when J is pressed while modifiers are held,
    # and not if someone was holding J and then pressed Ctrl + Shift.
    j_pressed_now = is_j_key(key)

    if ctrl_held and shift_held and j_pressed_now:
        # Latch: fire only once, avoiding repeated triggers while keys are held down
        if not shortcut_triggered:
            shortcut_triggered = True
            print("Shortcut detected: Ctrl + Shift + J", flush=True)


def on_release(key):
    """
    Called whenever any key is released.
    Removes key from pressed_keys and resets the trigger latch when needed.
    """
    global shortcut_triggered

    pressed_keys.discard(key)

    # If any key involved in the shortcut is released, reset the latch
    # so the shortcut can be triggered again on the next fresh press.
    if is_shortcut_key(key):
        shortcut_triggered = False

    # Pressing Esc stops the listener cleanly by returning False
    if key == keyboard.Key.esc:
        print("\nEsc pressed. Exiting...", flush=True)
        return False


def main():
    print("=" * 50, flush=True)
    print("Kya-Ray - Version 1: Keyboard Shortcut Listener", flush=True)
    print("=" * 50, flush=True)
    print("Instructions:", flush=True)
    print("  * Press Ctrl + Shift + J anywhere to trigger.", flush=True)
    print("  * Hold the keys to verify it triggers only once.", flush=True)
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