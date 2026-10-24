import json
import queue
import threading
import time
import tkinter as tk
from tkinter import scrolledtext
import urllib.error
import urllib.request
import pyperclip
from pynput import keyboard

# ==============================================================================
# Configuration & Constants
# ==============================================================================

# Ollama local API settings
OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3.2:1b"
REQUEST_TIMEOUT_SECONDS = 30

# Sets of modifier keys to track (supports both left and right keys)
CTRL_KEYS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}

# State variables for hotkey handling
pressed_keys = set()
shortcut_triggered = False

# Controller used to simulate keyboard events (e.g. Ctrl + C)
keyboard_controller = keyboard.Controller()

# Thread-safe queue for passing events from background threads to Tkinter's main UI thread
ui_queue = queue.Queue()

# Global reference to the keyboard listener
keyboard_listener = None


# ==============================================================================
# Local AI Helper (Ollama)
# ==============================================================================

def request_ai_explanation(text):
    """
    Sends selected text to the local Ollama API to generate a concise explanation.
    Uses Python's built-in urllib standard library (no extra pip packages needed).

    Returns:
        (success: bool, content: str)
        If success is True, content is the generated explanation.
        If success is False, content is a user-friendly error message.
    """
    prompt = (
        "Explain the following selected text concisely and in simple, beginner-friendly terms "
        f"(2 to 3 sentences max):\n\n\"{text.strip()}\""
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,  # Request the complete response at once
    }

    # Encode JSON payload to bytes for HTTP POST
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if response.status == 200:
                raw_body = response.read().decode("utf-8")
                parsed_json = json.loads(raw_body)
                explanation = parsed_json.get("response", "").strip()

                if explanation:
                    return True, explanation
                return False, "Ollama returned an empty response."
            else:
                return False, f"Ollama HTTP {response.status}: {response.reason}"

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False, f"Model '{OLLAMA_MODEL}' was not found in Ollama. Run 'ollama pull {OLLAMA_MODEL}'."
        return False, f"Ollama HTTP error {error.code}: {error.reason}"

    except urllib.error.URLError:
        return False, "Could not connect to Ollama at http://127.0.0.1:11434. Please ensure the Ollama app is running."

    except TimeoutError:
        return False, f"Request timed out after {REQUEST_TIMEOUT_SECONDS}s waiting for Ollama to respond."

    except Exception as error:
        return False, f"Unexpected error while contacting Ollama: {error}"


# ==============================================================================
# GUI: Response Window (Tkinter)
# ==============================================================================

class ResponseWindow:
    """
    Tkinter desktop window that displays captured text and AI explanations.
    All widget creation and updates run strictly on the main UI thread.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Kya-Ray")
        self.root.geometry("520x360")
        self.root.minsize(380, 240)

        # Main frame with margins
        frame = tk.Frame(root, padx=12, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        # Header label
        self.header_label = tk.Label(
            frame,
            text="Kya-Ray AI",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        self.header_label.pack(fill=tk.X, pady=(0, 6))

        # Scrollable text area to display selected text and explanations
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
            "Select text in any application and press Ctrl + Shift + J to receive an AI explanation.\n\nPress Esc to exit.",
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

        # Start checking the queue for events sent from background threads
        self.check_queue()

    def _bring_to_front(self):
        """Helper to ensure the window is visible and elevated above other windows."""
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after_idle(self.root.attributes, "-topmost", False)

    def show_generating(self, selected_text):
        """Displays generating state while Ollama processes the text."""
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)

        self.header_label.config(text="Generating Explanation...", fg="#2980b9")
        self.status_label.config(text=f"Thinking with {OLLAMA_MODEL}...")

        preview = selected_text if len(selected_text) <= 300 else selected_text[:300] + "..."
        content = (
            f"Selected Text:\n\"{preview}\"\n\n"
            f"Generating concise explanation using local AI ({OLLAMA_MODEL}). Please wait a moment..."
        )
        self.text_area.insert(tk.END, content)
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

    def show_explanation(self, selected_text, explanation):
        """Displays the AI-generated explanation when ready."""
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)

        self.header_label.config(text="AI Explanation", fg="#27ae60")
        self.status_label.config(text="Explanation ready")

        content = (
            f"Explanation:\n{explanation}\n\n"
            f"--------------------------------------------------\n"
            f"Selected Text:\n{selected_text}"
        )
        self.text_area.insert(tk.END, content)
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

    def show_error(self, selected_text, error_message):
        """Displays error details if Ollama inference fails."""
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)

        self.header_label.config(text="Explanation Failed", fg="#c0392b")
        self.status_label.config(text="Failed to generate explanation")

        content = (
            f"Could not generate an explanation.\n\n"
            f"Error details:\n{error_message}\n\n"
            f"--------------------------------------------------\n"
            f"Selected Text:\n{selected_text}"
        )
        self.text_area.insert(tk.END, content)
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

    def show_no_selection(self):
        """Displays notice when user triggered the shortcut with nothing selected."""
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)

        self.header_label.config(text="No Selection Detected", fg="#e67e22")
        self.status_label.config(text="No text selected")
        self.text_area.insert(
            tk.END,
            "No text was selected.\n\nPlease highlight some text in any window and press Ctrl + Shift + J again.",
        )
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

    def display_text(self, text):
        """Legacy helper from V3: displays raw text. Preserved for backwards compatibility."""
        if text and text.strip():
            self.show_generating(text)
        else:
            self.show_no_selection()

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
                if action == "generating":
                    self.show_generating(payload)
                elif action == "explanation_ready":
                    self.show_explanation(payload["text"], payload["explanation"])
                elif action == "explanation_error":
                    self.show_error(payload["text"], payload["error"])
                elif action == "no_selection":
                    self.show_no_selection()
                elif action == "show_text":
                    self.display_text(payload)
                elif action == "quit":
                    self.on_exit()
                    return
        except Exception as error:
            print(f"[Warning] Error polling UI queue: {error}", flush=True)

        self.root.after(50, self.check_queue)


# ==============================================================================
# Keyboard & Shortcut Detection (V1 - V2)
# ==============================================================================

def is_j_key(key):
    """
    Check if a key event represents the letter 'J'.
    On Windows, when Ctrl is held down, pynput often translates 'J'
    into a control character ('\n', ASCII 10) instead of 'j'.
    We check both the virtual key code (vk=74) and character representations.
    """
    if isinstance(key, keyboard.KeyCode):
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
    try:
        previous_clipboard = pyperclip.paste()
    except Exception:
        previous_clipboard = ""

    selected_text = ""
    try:
        pyperclip.copy("")
        time.sleep(0.02)

        # Temporarily release Shift so the active app registers 'Ctrl + C'
        keyboard_controller.release(keyboard.Key.shift)
        keyboard_controller.release(keyboard.Key.shift_l)
        keyboard_controller.release(keyboard.Key.shift_r)

        # Simulate pressing Ctrl + C to copy the highlighted text
        with keyboard_controller.pressed(keyboard.Key.ctrl):
            keyboard_controller.tap("c")

        time.sleep(0.08)
        selected_text = pyperclip.paste()

    except Exception as error:
        print(f"[Warning] Error during text capture: {error}", flush=True)

    finally:
        # Restore previous clipboard content
        try:
            pyperclip.copy(previous_clipboard)
        except Exception:
            pass

    return selected_text


def process_shortcut_event():
    """
    Runs in a background thread when Ctrl + Shift + J is triggered.
    Steps:
    1. Captures selected text without blocking the UI.
    2. If no text is selected, tells the UI to notify the user.
    3. If text is selected, immediately opens UI with 'Generating...' status.
    4. Makes non-blocking local HTTP request to Ollama (llama3.2:1b).
    5. Posts final explanation (or error message) to the UI queue.
    """
    print("\n--- Shortcut detected: Ctrl + Shift + J ---", flush=True)
    captured_text = capture_selected_text()

    if not captured_text or not captured_text.strip():
        print("[No text selected]\n", flush=True)
        ui_queue.put(("no_selection", None))
        return

    print("Captured text:", flush=True)
    print(captured_text, flush=True)
    print("------------------------------------------", flush=True)
    print("Requesting AI explanation from Ollama (llama3.2:1b)...", flush=True)

    # Immediately pop up the window showing 'Generating...'
    ui_queue.put(("generating", captured_text))

    # Perform Ollama inference in this background thread
    success, result = request_ai_explanation(captured_text)

    if success:
        print("Explanation generated successfully:", flush=True)
        print(result, flush=True)
        print("------------------------------------------\n", flush=True)
        ui_queue.put(("explanation_ready", {"text": captured_text, "explanation": result}))
    else:
        print(f"[Error] Failed to generate explanation: {result}\n", flush=True)
        ui_queue.put(("explanation_error", {"text": captured_text, "error": result}))


def on_press(key):
    """
    Called whenever any key is pressed down.
    Adds key to pressed_keys and checks if the shortcut was just completed.
    """
    global shortcut_triggered

    pressed_keys.add(key)

    ctrl_held = any(k in pressed_keys for k in CTRL_KEYS)
    shift_held = any(k in pressed_keys for k in SHIFT_KEYS)
    j_pressed_now = is_j_key(key)

    if ctrl_held and shift_held and j_pressed_now:
        if not shortcut_triggered:
            shortcut_triggered = True
            # Run capture & inference in a background daemon thread
            threading.Thread(target=process_shortcut_event, daemon=True).start()


def on_release(key):
    """
    Called whenever any key is released.
    Removes key from pressed_keys and resets the trigger latch when needed.
    """
    global shortcut_triggered

    pressed_keys.discard(key)

    if is_shortcut_key(key):
        shortcut_triggered = False

    # Esc stops the listener cleanly and tells Tkinter to close
    if key == keyboard.Key.esc:
        print("\nEsc pressed. Exiting...", flush=True)
        ui_queue.put(("quit", None))
        return False


def main():
    global keyboard_listener

    print("=" * 60, flush=True)
    print("Kya-Ray - Version 5: AI Explanation Integration", flush=True)
    print("=" * 60, flush=True)
    print("Instructions:", flush=True)
    print("  * Select text in any window and press Ctrl + Shift + J.", flush=True)
    print("  * The response window will pop up and stream/display an AI explanation.", flush=True)
    print("  * Powered locally by Ollama with model 'llama3.2:1b'.", flush=True)
    print("  * Click 'Close' on the window to dismiss it.", flush=True)
    print("  * Press Esc (or close the window with 'X') to exit.", flush=True)
    print("=" * 60 + "\n", flush=True)

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