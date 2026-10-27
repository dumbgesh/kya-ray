import ctypes
from ctypes import wintypes
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
# Profiler Telemetry Hook (V7 - Temporary Instrumentation)
# ==============================================================================
PROFILER_PORT = 49999
_profiler_sock = None
_run_counter = 0

ALLOWED_METRIC_KEYS = (
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
    "prompt_eval_count",
    "eval_count",
)


def sanitize_ollama_metrics(raw_metrics):
    """
    Extracts and sanitizes ONLY numeric timing and token count metadata.
    Guarantees strict privacy: zero user text, prompt, or response content is kept.
    Missing, non-numeric, or negative fields are stored as None (unavailable).
    """
    if not isinstance(raw_metrics, dict):
        return None
    sanitized = {}
    for key in ALLOWED_METRIC_KEYS:
        val = raw_metrics.get(key)
        # Ensure only numbers (int/float, excluding bool) >= 0 are accepted
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
            sanitized[key] = val
        else:
            sanitized[key] = None
    return sanitized


def emit_profile_event(event_name, run_id, error=None, metrics=None):
    """
    Sends lightweight, non-blocking telemetry event to local profiler.
    Payload contains ONLY run_id, event name, monotonic timestamp, error category,
    and optional numeric-only Ollama timing/token metrics.
    Zero prompt, text, or explanation content is ever transmitted.
    """
    global _profiler_sock
    try:
        if _profiler_sock is None:
            import socket
            _profiler_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payload = {
            "run_id": run_id,
            "event": event_name,
            "ts": time.perf_counter(),
            "error": error,
        }
        if metrics is not None:
            sanitized = sanitize_ollama_metrics(metrics)
            if sanitized is not None:
                payload["metrics"] = sanitized
        packet = json.dumps(payload).encode("utf-8")
        _profiler_sock.sendto(packet, ("127.0.0.1", PROFILER_PORT))
    except Exception:
        pass


# ==============================================================================
# Windows Screen & Cursor Helper (ctypes)
# ==============================================================================

class POINT(ctypes.Structure):
    """Win32 POINT structure representing (x, y) screen coordinates."""
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def get_mouse_position():
    """
    Retrieves the current global mouse cursor position on Windows.
    Returns:
        (x, y) tuple if successful, or None if inaccessible (e.g., non-interactive session).
    """
    try:
        pt = POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
    except Exception:
        pass
    return None


# ==============================================================================
# Local AI Helper (Ollama)
# ==============================================================================

def request_ai_explanation(text):
    """
    Sends selected text to the local Ollama API to generate a concise explanation.
    Uses Python's built-in urllib standard library (no extra pip packages needed).

    Returns:
        (success: bool, content: str, metrics: dict | None)
        If success is True, content is the generated explanation,
        and metrics contains Ollama's numeric timing/token fields (or None if unavailable).
        If success is False, content is a user-friendly error message, and metrics is None.
    """
    prompt = (
        "Explain the following selected text concisely and in simple, beginner-friendly terms "
        f"(2 to 3 sentences max):\n\n\"{text.strip()}\""
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,  # Request the complete response at once
        "options": {
            "num_predict": 45,
        },
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
                metrics = sanitize_ollama_metrics(parsed_json)

                if explanation:
                    return True, explanation, metrics
                return False, "Ollama returned an empty response.", None
            else:
                return False, f"Ollama HTTP {response.status}: {response.reason}", None

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False, f"Model '{OLLAMA_MODEL}' was not found in Ollama. Run 'ollama pull {OLLAMA_MODEL}'.", None
        return False, f"Ollama HTTP error {error.code}: {error.reason}", None

    except urllib.error.URLError:
        return False, "Could not connect to Ollama at http://127.0.0.1:11434. Please ensure the Ollama app is running.", None

    except TimeoutError:
        return False, f"Request timed out after {REQUEST_TIMEOUT_SECONDS}s waiting for Ollama to respond.", None

    except Exception as error:
        return False, f"Unexpected error while contacting Ollama: {error}", None


# ==============================================================================
# GUI: Floating Speech-Bubble Window (Tkinter)
# ==============================================================================

class FloatingBubbleWindow:
    """
    Compact, floating speech-bubble interface for Kya-Ray.

    Key characteristics:
    1. Borderless floating card styling via root.overrideredirect(True).
    2. Pinned permanently above normal application windows (including VS Code)
       via root.attributes("-topmost", True).
    3. Context-aware positioning near the active mouse pointer, clamped to screen edges.
    4. Draggable header allowing users to easily reposition the bubble anywhere.
    5. Minimalist header with '✕' dismiss button, status badge, and bottom close control.
    6. Thread-safe updates from background inference via ui_queue.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Kya-Ray")

        # Dimensions of the compact floating bubble
        self.width = 440
        self.height = 290

        # Enable borderless floating window and topmost pinning
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        # Variables to track window dragging
        self._drag_start_x = 0
        self._drag_start_y = 0

        # Position bubble initially
        self.position_bubble()

        # Outer frame with a glowing accent border (slate/sky-blue palette)
        self.outer_frame = tk.Frame(
            root,
            bg="#1e293b",               # Slate-800 dark background
            highlightbackground="#38bdf8", # Sky blue glowing 1px border
            highlightcolor="#38bdf8",
            highlightthickness=1,
            padx=0,
            pady=0,
        )
        self.outer_frame.pack(fill=tk.BOTH, expand=True)

        # ----------------------------------------------------------------------
        # Header bar (Draggable)
        # ----------------------------------------------------------------------
        self.header_frame = tk.Frame(
            self.outer_frame,
            bg="#0f172a",               # Slate-900 contrasting header
            padx=10,
            pady=6,
            cursor="fleur",             # Move cursor to signal draggability
        )
        self.header_frame.pack(fill=tk.X)

        # Brand / Title label
        self.title_label = tk.Label(
            self.header_frame,
            text="💬 Kya-Ray",
            font=("Segoe UI", 10, "bold"),
            fg="#38bdf8",
            bg="#0f172a",
            cursor="fleur",
        )
        self.title_label.pack(side=tk.LEFT)

        # Status badge indicator
        self.header_status = tk.Label(
            self.header_frame,
            text="Ready",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#0f172a",
            cursor="fleur",
        )
        self.header_status.pack(side=tk.LEFT, padx=(10, 0))

        # Close button ('✕')
        self.close_x_btn = tk.Label(
            self.header_frame,
            text=" ✕ ",
            font=("Segoe UI", 10, "bold"),
            fg="#94a3b8",
            bg="#0f172a",
            cursor="hand2",
        )
        self.close_x_btn.pack(side=tk.RIGHT)
        self.close_x_btn.bind("<Button-1>", lambda e: self.hide_window())
        self.close_x_btn.bind("<Enter>", lambda e: self.close_x_btn.config(fg="#f87171"))
        self.close_x_btn.bind("<Leave>", lambda e: self.close_x_btn.config(fg="#94a3b8"))

        # Bind mouse drag events to the header elements
        for widget in (self.header_frame, self.title_label, self.header_status):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)

        # ----------------------------------------------------------------------
        # Body frame (Text Area)
        # ----------------------------------------------------------------------
        body_frame = tk.Frame(self.outer_frame, bg="#1e293b", padx=10, pady=8)
        body_frame.pack(fill=tk.BOTH, expand=True)

        self.text_area = scrolledtext.ScrolledText(
            body_frame,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            bg="#0f172a",
            fg="#f8fafc",
            insertbackground="#f8fafc",
            selectbackground="#0284c7",
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)
        self.text_area.insert(
            tk.END,
            "Select text in any window and press Ctrl + Shift + J.\n\n"
            "Kya-Ray will provide a concise explanation in this floating bubble.\n\n"
            "Press Esc to exit the application.",
        )
        self.text_area.config(state=tk.DISABLED)

        # ----------------------------------------------------------------------
        # Footer frame (Minimal Controls)
        # ----------------------------------------------------------------------
        footer_frame = tk.Frame(self.outer_frame, bg="#0f172a", padx=10, pady=5)
        footer_frame.pack(fill=tk.X)

        self.footer_hint = tk.Label(
            footer_frame,
            text="Drag header to move • Esc to exit",
            font=("Segoe UI", 8),
            fg="#64748b",
            bg="#0f172a",
        )
        self.footer_hint.pack(side=tk.LEFT)

        self.dismiss_btn = tk.Button(
            footer_frame,
            text="Close",
            font=("Segoe UI", 9),
            bg="#334155",
            fg="#f8fafc",
            activebackground="#475569",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=10,
            pady=1,
            cursor="hand2",
            command=self.hide_window,
        )
        self.dismiss_btn.pack(side=tk.RIGHT)

        # Start checking the queue for events sent from background threads
        self.check_queue()

    def start_drag(self, event):
        """Records initial pointer offset when user starts dragging the header."""
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def do_drag(self, event):
        """Moves the window in real-time as the user drags with mouse button held."""
        deltax = event.x - self._drag_start_x
        deltay = event.y - self._drag_start_y
        new_x = self.root.winfo_x() + deltax
        new_y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{new_x}+{new_y}")

    def position_bubble(self):
        """
        Positions the floating speech bubble on screen.
        1. Attempts to anchor near active mouse cursor (+15px, +15px).
        2. Clamps the coordinates so the bubble never overflows monitor edges or taskbars.
        3. Falls back to a clean upper-center placement if cursor position is unavailable.
        """
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        # Sensible fallback: horizontally centered in upper third of primary monitor
        target_x = max(20, (screen_w - self.width) // 2)
        target_y = max(40, (screen_h - self.height) // 3)

        # Attempt cursor-based positioning
        mouse_pos = get_mouse_position()
        if mouse_pos:
            mx, my = mouse_pos
            if 0 <= mx < screen_w and 0 <= my < screen_h:
                target_x = mx + 15
                target_y = my + 15

        # Clamp within visible screen boundaries
        if target_x + self.width > screen_w - 15:
            target_x = screen_w - self.width - 15
        if target_y + self.height > screen_h - 45:
            # If bottom would overflow, position above cursor if space permits
            if mouse_pos and (mouse_pos[1] - self.height - 15) >= 15:
                target_y = mouse_pos[1] - self.height - 15
            else:
                target_y = screen_h - self.height - 45

        if target_x < 15:
            target_x = 15
        if target_y < 15:
            target_y = 15

        self.root.geometry(f"{self.width}x{self.height}+{target_x}+{target_y}")

    def _bring_to_front(self):
        """
        Ensures the floating bubble is visible and stays permanently pinned above
        normal application windows (including VS Code).
        Note: We NEVER reset -topmost to False, ensuring it floats reliably.
        """
        self.root.deiconify()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()

    def show_generating(self, selected_text):
        """Displays generating state while Ollama processes the text."""
        self.position_bubble()
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)

        self.header_status.config(text=f"Thinking with {OLLAMA_MODEL}...", fg="#38bdf8")

        preview = selected_text if len(selected_text) <= 220 else selected_text[:220] + "..."
        content = (
            f"Selected Text:\n\"{preview}\"\n\n"
            f"Thinking with local AI ({OLLAMA_MODEL}). Please wait a moment..."
        )
        self.text_area.insert(tk.END, content)
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

    def show_explanation(self, selected_text, explanation, run_id=None):
        """Displays the AI-generated explanation when ready."""
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)

        self.header_status.config(text="Ready", fg="#4ade80")

        content = (
            f"Explanation:\n{explanation}\n\n"
            f"--------------------------------------------------\n"
            f"Selected Text:\n{selected_text}"
        )
        self.text_area.insert(tk.END, content)
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

        # Flush pending widget redraw and geometry calculations synchronously
        self.root.update_idletasks()

        # Profiler hook: record the moment Tkinter has processed the answer update
        if run_id is not None:
            emit_profile_event("answer_displayed", run_id)

    def show_error(self, selected_text, error_message):
        """Displays error details if Ollama inference fails."""
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)

        self.header_status.config(text="Explanation Failed", fg="#f87171")

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
        self.position_bubble()
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)

        self.header_status.config(text="No Selection", fg="#fbbf24")
        self.text_area.insert(
            tk.END,
            "No text was selected.\n\n"
            "Please highlight some text in any window and press Ctrl + Shift + J again.",
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
        """Hides the bubble when dismissed by the user."""
        self.root.withdraw()
        print("Bubble dismissed. Press Ctrl + Shift + J to show it again, or Esc to exit.", flush=True)

    def on_exit(self):
        """Cleanly terminates the application when exiting."""
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
                    text = payload.get("text", "") if isinstance(payload, dict) else payload
                    self.show_generating(text)
                elif action == "explanation_ready":
                    run_id = payload.get("run_id") if isinstance(payload, dict) else None
                    self.show_explanation(payload["text"], payload["explanation"], run_id=run_id)
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


# Alias for backward compatibility with existing tests
ResponseWindow = FloatingBubbleWindow


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


def process_shortcut_event(run_id=None):
    """
    Runs in a background thread when Ctrl + Shift + J is triggered.
    Steps:
    1. Captures selected text without blocking the UI.
    2. If no text is selected, tells the UI to notify the user.
    3. If text is selected, immediately opens UI with 'Thinking...' status.
    4. Makes non-blocking local HTTP request to Ollama (llama3.2:1b).
    5. Posts final explanation (or error message) to the UI queue.
    """
    if run_id is not None:
        emit_profile_event("activation_started", run_id)

    print("\n--- Shortcut detected: Ctrl + Shift + J ---", flush=True)

    if run_id is not None:
        emit_profile_event("text_capture_started", run_id)
    captured_text = capture_selected_text()
    if run_id is not None:
        emit_profile_event("text_capture_completed", run_id)

    if not captured_text or not captured_text.strip():
        print("[No text selected]\n", flush=True)
        if run_id is not None:
            emit_profile_event("pipeline_aborted", run_id, error="no_selection")
        ui_queue.put(("no_selection", {"run_id": run_id}))
        return

    print("Captured text:", flush=True)
    print(captured_text, flush=True)
    print("------------------------------------------", flush=True)
    print("Requesting AI explanation from Ollama (llama3.2:1b)...", flush=True)

    # Immediately pop up the floating bubble showing 'Thinking...'
    ui_queue.put(("generating", {"text": captured_text, "run_id": run_id}))

    # Perform Ollama inference in this background thread
    if run_id is not None:
        emit_profile_event("ollama_request_started", run_id)
    success, result, metrics = request_ai_explanation(captured_text)
    if run_id is not None:
        emit_profile_event(
            "ollama_response_received",
            run_id,
            error=None if success else "ollama_error",
            metrics=metrics if success else None,
        )

    if success:
        print("Explanation generated successfully:", flush=True)
        print(result, flush=True)
        print("------------------------------------------\n", flush=True)
        if run_id is not None:
            emit_profile_event("ui_update_queued", run_id)
        ui_queue.put(("explanation_ready", {"text": captured_text, "explanation": result, "run_id": run_id}))
    else:
        print(f"[Error] Failed to generate explanation: {result}\n", flush=True)
        if run_id is not None:
            emit_profile_event("pipeline_aborted", run_id, error="ollama_failed")
        ui_queue.put(("explanation_error", {"text": captured_text, "error": result, "run_id": run_id}))


def on_press(key):
    """
    Called whenever any key is pressed down.
    Adds key to pressed_keys and checks if the shortcut was just completed.
    """
    global shortcut_triggered, _run_counter

    pressed_keys.add(key)

    ctrl_held = any(k in pressed_keys for k in CTRL_KEYS)
    shift_held = any(k in pressed_keys for k in SHIFT_KEYS)
    j_pressed_now = is_j_key(key)

    if ctrl_held and shift_held and j_pressed_now:
        if not shortcut_triggered:
            shortcut_triggered = True
            # Assign unique run ID explicitly for this activation
            _run_counter += 1
            run_id = _run_counter
            emit_profile_event("hotkey_detected", run_id)
            # Run capture & inference in background daemon thread with explicit run_id
            threading.Thread(target=process_shortcut_event, args=(run_id,), daemon=True).start()


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
    print("Kya-Ray - Version 6: Floating Speech-Bubble UI", flush=True)
    print("=" * 60, flush=True)
    print("Instructions:", flush=True)
    print("  * Select text in any window and press Ctrl + Shift + J.", flush=True)
    print("  * A floating speech-bubble appears above your active app.", flush=True)
    print("  * Pinned topmost: stays visible even when clicking VS Code.", flush=True)
    print("  * Drag the bubble header to reposition it anywhere.", flush=True)
    print("  * Click [X] or 'Close' to dismiss the bubble.", flush=True)
    print("  * Press Esc to exit the application completely.", flush=True)
    print("=" * 60 + "\n", flush=True)

    root = tk.Tk()
    app = FloatingBubbleWindow(root)

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