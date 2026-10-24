import queue
import threading
import time
import tkinter as tk
from tkinter import scrolledtext
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

# Thread-safe queue for passing captured text to the Tkinter main UI thread
ui_queue = queue.Queue()

# Reference to the keyboard listener
keyboard_listener = None


class ResponseWindow:
    """
    Tkinter desktop window that displays the captured text.
    Must be created and manipulated only on the main UI thread.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Kya-Ray")
        self.root.geometry("480x320")
        self.root.minsize(360, 220)

        # Main frame with margins
        frame = tk.Frame(root, padx=12, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        # Header label
        self.header_label = tk.Label(
            frame,
            text="Captured Text",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        self.header_label.pack(fill=tk.X, pady=(0, 6))

        # Scrollable text area to display selected text
        self.text_area = scrolledtext.ScrolledText(
            frame,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            padx=8,
            pady=8,
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)
        self.text_area.insert(
            tk.END,
            "Select text in any application and press Ctrl + Shift + J to display it here.\n\nPress Esc to exit.",
        )
        self.text_area.config(state=tk.DISABLED)

        # Bottom row for status message and close button
        bottom_frame = tk.Frame(frame, pady=6)
        bottom_frame.pack(fill=tk.X)

        self.status_label = tk.Label(
            bottom_frame,
            text="Ready (Ctrl + Shift + J)",
            font=("Segoe UI", 9),
            fg="#555555",
            anchor="w",
        )
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.close_btn = tk.Button(
            bottom_frame,
            text="Close",
            width=10,
            command=self.hide_window,
        )
        self.close_btn.pack(side=tk.RIGHT)

        # Handle window 'X' button
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

        # Start checking the queue for new text from the background thread
        self.check_queue()

    def display_text(self, text):
        """Updates text area content. Runs on the main UI thread."""
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)

        if text and text.strip():
            self.header_label.config(text="Captured Text", fg="#2c3e50")
            self.status_label.config(text="Text captured successfully")
            self.text_area.insert(tk.END, text)
        else:
            self.header_label.config(text="No Selection Detected", fg="#c0392b")
            self.status_label.config(text="No text selected")
            self.text_area.insert(
                tk.END,
                "No text was selected.\n\nPlease highlight some text in any window and press Ctrl + Shift + J again.",
            )

        self.text_area.config(state=tk.DISABLED)

        # Make sure the window is visible and brought to the front
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after_idle(self.root.attributes, "-topmost", False)

    def hide_window(self):
        """Hides the window when the user clicks 'Close'."""
        self.root.withdraw()
        print("Window dismissed. Press Ctrl + Shift + J to show it again, or Esc to exit.", flush=True)

    def on_exit(self):
        """Cleanly terminates the application when the window is closed."""
        print("\nWindow closed. Exiting...", flush=True)
        if keyboard_listener and keyboard_listener.is_alive():
            keyboard_listener.stop()
        self.root.destroy()

    def check_queue(self):
        """
        Polls the queue every 50ms for events sent from background threads.
        This ensures Tkinter widgets are only ever modified on the main thread.
        """
        try:
            while not ui_queue.empty():
                action, payload = ui_queue.get_nowait()
                if action == "show_text":
                    self.display_text(payload)
                elif action == "quit":
                    self.on_exit()
                    return
        except Exception as error:
            print(f"[Warning] Error polling UI queue: {error}", flush=True)

        self.root.after(50, self.check_queue)


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
    Captures selected text, prints to terminal (V2), and queues UI update (V3).
    """
    print("\n--- Shortcut detected: Ctrl + Shift + J ---", flush=True)
    captured_text = capture_selected_text()

    if captured_text and captured_text.strip():
        print("Captured text:", flush=True)
        print(captured_text, flush=True)
        print("------------------------------------------\n", flush=True)
    else:
        print("[No text selected]\n", flush=True)

    # Safely forward captured text to the Tkinter main thread via queue
    ui_queue.put(("show_text", captured_text))


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

    # Pressing Esc stops the listener cleanly and tells Tkinter to close
    if key == keyboard.Key.esc:
        print("\nEsc pressed. Exiting...", flush=True)
        ui_queue.put(("quit", None))
        return False


def main():
    global keyboard_listener

    print("=" * 50, flush=True)
    print("Kya-Ray - Version 3: Basic Response Window", flush=True)
    print("=" * 50, flush=True)
    print("Instructions:", flush=True)
    print("  * Select text in any window and press Ctrl + Shift + J.", flush=True)
    print("  * Captured text appears in the response window and terminal.", flush=True)
    print("  * Click 'Close' on the window to dismiss it.", flush=True)
    print("  * Press Esc (or close the window with 'X') to exit.", flush=True)
    print("=" * 50 + "\n", flush=True)

    root = tk.Tk()
    app = ResponseWindow(root)

    try:
        keyboard_listener = keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
        )
        keyboard_listener.start()
    except Exception as error:
        print(f"\n[Error] Failed to start keyboard listener: {error}", flush=True)
        print("Please ensure your terminal has appropriate permissions to monitor keyboard input.", flush=True)
        return

    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...", flush=True)
    finally:
        if keyboard_listener and keyboard_listener.is_alive():
            keyboard_listener.stop()


if __name__ == "__main__":
    main()