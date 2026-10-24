from pynput import keyboard

pressed_keys = set()
shortcut_triggered = False


def on_press(key):
    global shortcut_triggered

    pressed_keys.add(key)

    ctrl_pressed = (
        keyboard.Key.ctrl_l in pressed_keys
        or keyboard.Key.ctrl_r in pressed_keys
    )

    shift_pressed = (
        keyboard.Key.shift in pressed_keys
        or keyboard.Key.shift_l in pressed_keys
        or keyboard.Key.shift_r in pressed_keys
    )

    is_j = (
        isinstance(key, keyboard.KeyCode)
        and key.char is not None
        and key.char.lower() == "j"
    )

    if ctrl_pressed and shift_pressed and is_j:
        if not shortcut_triggered:
            shortcut_triggered = True
            print("\nShortcut detected: Ctrl + Shift + J")


def on_release(key):
    global shortcut_triggered

    pressed_keys.discard(key)

    if key in {
        keyboard.Key.ctrl_l,
        keyboard.Key.ctrl_r,
        keyboard.Key.shift,
        keyboard.Key.shift_l,
        keyboard.Key.shift_r,
    }:
        shortcut_triggered = False

    if isinstance(key, keyboard.KeyCode):
        if key.char is not None and key.char.lower() == "j":
            shortcut_triggered = False

    if key == keyboard.Key.esc:
        return False


print("kya-ray shortcut test running")
print("Press Ctrl + Shift + J anywhere.")
print("Press Esc to exit.\n")

with keyboard.Listener(
    on_press=on_press,
    on_release=on_release,
) as listener:
    listener.join()