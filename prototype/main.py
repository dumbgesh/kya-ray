from pynput import keyboard

SHORTCUT_KEYS = {
    keyboard.Key.ctrl_l,
    keyboard.Key.shift,
}

pressed_keys = set()

def on_press(key):
    pressed_keys.add(key)

    ctrl_pressed = (
        keyboard.Key.ctrl_l in pressed_keys
        or keyboard.Key.ctrl_r in pressed_keys
    )
    shift_pressed = (
        keyboard.Key.shift in pressed_keys
        or keyboard.Key.shift_r in pressed_keys
        or keyboard.Key.shift_l in pressed_keys
    )

    if ctrl_pressed and shift_pressed:
        print("\nShortcut detected: Ctrl + Shift + J")


def on_release(key):
    pressed_keys.discard(key)


print("kya ray — shortcut test running")
print("Press Ctrl + Shift + J anywhere.")
print("Press Esc to exit.\n")

with keyboard.Listener(
    on_press=on_press,
    on_release=on_release,
) as listener:
    listener.join()