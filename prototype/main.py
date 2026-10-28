import ctypes
from ctypes import wintypes
import json
import math
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
# Intent Taxonomy & Selection (Hyphen Features)
# ==============================================================================

CORE_INTENTS = ("-explain", "-summarize", "-code", "-create")

# Terminal CLI tool names that signal terminal commands
CLI_COMMANDS = {
    "git", "npm", "npx", "pip", "docker", "curl", "wget", "cd", "ls", "dir",
    "grep", "pytest", "python", "node", "cargo", "go", "kubectl", "make",
    "cat", "chmod", "chown", "sudo", "ssh", "powershell", "yarn", "pnpm",
}

# Programming language keywords and patterns
CODE_KEYWORDS = {
    "def ", "class ", "function ", "return ", "import ",
    "const ", "let ", "var ", "public ", "private ", "protected ",
    "void ", "struct ", "async ", "await ", "try:",
    "except ", "catch ", "finally:", "lambda ", "fn ", "impl ",
}

# Error and traceback indicators
CODE_ERROR_INDICATORS = (
    "traceback (most recent call last)",
    "syntaxerror:",
    "typeerror:",
    "referenceerror:",
    "nameerror:",
    "indexerror:",
    "keyerror:",
    "valueerror:",
    "attributeerror:",
    "nullpointerexception",
    "at line ",
    "fatal:",
    "command not found",
    "error: ",
)

# Creation prompt trigger verbs and prefixes
CREATE_TRIGGERS = (
    "write a", "write an", "create a", "create an", "generate a", "generate an",
    "draft a", "draft an", "make a list of", "build a", "build an", "compose a",
    "compose an", "implement a", "implement an", "template for", "boilerplate for",
)

INTENT_INSTRUCTIONS = {
    "-explain": (
        "Explain the following selected text accurately in simple, beginner-friendly language in 1 to 2 complete sentences. "
        "If the term is ambiguous or unfamiliar, acknowledge uncertainty and avoid inventing origins, people, places, or facts. "
        "Distinguish claims contained in selected text from verified facts; do not automatically endorse unsupported claims. "
        "Never invent command execution results, error messages, or reasons for failure. "
        "If the text contains a likely typo (such as 'CLRF' for 'CRLF' line endings), identify the typo and the likely intended term. "
        "Finish cleanly without trailing off or starting an incomplete sentence."
    ),
    "-summarize": (
        "Summarize the essential meaning of the following text in 1 to 2 short, complete sentences. "
        "Capture the key takeaways concisely and finish cleanly without trailing off or starting an incomplete sentence. "
        "Distinguish claims contained in selected text from verified facts; do not invent unsupported facts or execution results."
    ),
    "-code": (
        "Explain what the following code or terminal command actually does in 1 to 2 complete sentences. "
        "The input is only provided as text: do not claim it was executed or run, and never invent command execution results, error messages, or reasons for failure. "
        "Identify likely syntax errors, misspelled module names, or typos (such as 'panadas' for 'pandas') and state the obvious correction. "
        "Finish cleanly without trailing off or starting an incomplete sentence."
    ),
    "-create": (
        "Fulfill the following writing or drafting request directly and concisely. "
        "Treat routine requests (such as illness notifications or assignment extension requests) as legitimate; "
        "do not assume deception or refuse benign requests unless the text explicitly indicates dishonest intent. "
        "Generate the requested text directly without conversational preamble, finishing cleanly without trailing off or starting an incomplete sentence."
    ),
}


def infer_intent(text):
    """
    Infers the user's intended task from the highlighted content without
    requiring manual mode selection.

    Returns one of:
      - '-code': For terminal commands, code snippets, stack traces, errors.
      - '-create': For explicit artifact/content generation prompts.
      - '-summarize': For long prose, multi-paragraph text, meeting notes.
      - '-explain': For concepts, short terms, idioms, questions, and defaults.
    """
    if not text or not text.strip():
        return "-explain"

    raw = text.strip()
    lower = raw.lower()
    first_line = lower.splitlines()[0].strip() if lower.splitlines() else lower
    words = raw.split()
    word_count = len(words)

    # 1. Detect -create: explicit generation/creation directives
    for trigger in CREATE_TRIGGERS:
        if lower.startswith(trigger) or (word_count < 30 and trigger in lower):
            return "-create"

    # 2. Strong, explicit code signals (apply to all text lengths)
    # A. Stack traces and error messages
    for err in CODE_ERROR_INDICATORS:
        if err in lower:
            return "-code"

    # B. Syntax symbols common in code (brackets, operators, semicolons, arrows)
    has_code_symbols = (
        ("=>" in raw) or
        ("===" in raw) or
        ("!==" in raw) or
        ("{" in raw and "}" in raw and "\n" in raw) or
        (raw.endswith(";") and ("=" in raw or "(" in raw))
    )
    if has_code_symbols:
        return "-code"

    # C. Explicit code declarations
    has_explicit_code_def = any(
        line.strip().startswith(("def ", "class ", "function ", "async def ", "public class ", "import ", "interface "))
        or (line.strip().startswith("from ") and " import " in line)
        for line in raw.splitlines()
    )
    if has_explicit_code_def:
        return "-code"

    # 3. Detect -summarize:
    # Substantial natural language prose (>= 50 words, or multiple paragraphs / bulleted items >= 20 words)
    has_bullets = any(line.strip().startswith(("-", "*", "•")) for line in raw.splitlines())
    has_multiple_paragraphs = len([p for p in raw.split("\n\n") if p.strip()]) >= 2
    if word_count >= 50 or ((has_multiple_paragraphs or has_bullets) and word_count >= 20):
        return "-summarize"

    # 4. Short code snippets and terminal commands (< 50 words)
    # A. Common terminal commands (checked on short command lines)
    first_token = first_line.split()[0] if first_line.split() else ""
    if first_token in ("$", ">", "#") and len(first_line.split()) > 1:
        first_token = first_line.split()[1]
    if first_token in CLI_COMMANDS and word_count < 30:
        return "-code"

    # B. Language keywords / syntax constructs in short snippets
    if any(kw in raw for kw in CODE_KEYWORDS) or ("from " in raw and " import " in raw):
        return "-code"

    # 5. Default to -explain (concepts, phrases, single words, definitions)
    return "-explain"


def build_intent_prompt(text, intent):
    """Formats the intent-specific instruction prefix and user text."""
    prefix = INTENT_INSTRUCTIONS.get(intent, INTENT_INSTRUCTIONS["-explain"])
    return f"{prefix}\n\n\"{text.strip()}\""


class ExplanationResponse(tuple):
    """
    3-tuple (success, content, metrics) preserving complete backward compatibility,
    while also exposing .intent as an attribute and property.
    """
    def __new__(cls, success, content, metrics=None, intent="-explain"):
        obj = super().__new__(cls, (success, content, metrics))
        obj.intent = intent
        return obj

    @property
    def success(self):
        return self[0]

    @property
    def content(self):
        return self[1]

    @property
    def metrics(self):
        return self[2]


# ==============================================================================
# Response Sanitation & Truncation Protection
# ==============================================================================

def clean_truncated_sentence(text):
    """
    Ensures answers do not end with an arbitrary unfinished sentence fragment.
    If the response contains complete sentences followed by a trailing fragment
    without terminal punctuation, trims the trailing fragment.
    """
    if not text:
        return text

    stripped = text.strip()
    # Check if the stripped text already ends cleanly with terminal punctuation or code delimiters
    terminal_endings = (".", "!", "?", '."', ".'", '!"', "?'", '!)', '?)', '.)', "```", "`")
    if any(stripped.endswith(end) for end in terminal_endings):
        return stripped

    # Search for the last valid terminal punctuation mark
    last_punct_idx = -1
    for i, char in enumerate(stripped):
        if char in {".", "!", "?"}:
            # Avoid splitting on decimal points in numbers (e.g., 3.14)
            if i > 0 and i < len(stripped) - 1 and stripped[i - 1].isdigit() and stripped[i + 1].isdigit():
                continue
            last_punct_idx = i

    if last_punct_idx != -1:
        # Include any closing quotes, parentheses, brackets immediately following the punctuation
        end_idx = last_punct_idx + 1
        while end_idx < len(stripped) and stripped[end_idx] in ('"', "'", ")", "]", "}"):
            end_idx += 1
        return stripped[:end_idx].strip()

    return stripped


# ==============================================================================
# Local AI Helper (Ollama)
# ==============================================================================

def request_ai_explanation(text, intent=None):
    """
    Sends selected text to the local Ollama API to generate a concise response
    tailored to the inferred or specified intent (-explain, -summarize, -code, -create).

    Returns:
        ExplanationResponse (success: bool, content: str, metrics: dict | None)
        with .intent attribute denoting the intent applied.
    """
    if intent is None:
        intent = infer_intent(text)

    prompt = build_intent_prompt(text, intent)

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,  # Request the complete response at once
        "options": {
            "num_predict": 90,
            "temperature": 0.1,
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
                raw_explanation = parsed_json.get("response", "").strip()
                explanation = clean_truncated_sentence(raw_explanation)
                metrics = sanitize_ollama_metrics(parsed_json)

                if explanation:
                    return ExplanationResponse(True, explanation, metrics, intent=intent)
                return ExplanationResponse(False, "Ollama returned an empty response.", None, intent=intent)
            else:
                return ExplanationResponse(False, f"Ollama HTTP {response.status}: {response.reason}", None, intent=intent)

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return ExplanationResponse(False, f"Model '{OLLAMA_MODEL}' was not found in Ollama. Run 'ollama pull {OLLAMA_MODEL}'.", None, intent=intent)
        return ExplanationResponse(False, f"Ollama HTTP error {error.code}: {error.reason}", None, intent=intent)

    except urllib.error.URLError:
        return ExplanationResponse(False, "Could not connect to Ollama at http://127.0.0.1:11434. Please ensure the Ollama app is running.", None, intent=intent)

    except TimeoutError:
        return ExplanationResponse(False, f"Request timed out after {REQUEST_TIMEOUT_SECONDS}s waiting for Ollama to respond.", None, intent=intent)

    except Exception as error:
        return ExplanationResponse(False, f"Unexpected error while contacting Ollama: {error}", None, intent=intent)


# ==============================================================================
# GUI: Floating Speech-Bubble Window (Tkinter)
# ==============================================================================

def get_system_theme():
    """
    Detects Windows OS light/dark theme preference via registry.
    Returns a dictionary of cohesive colors for the comic speech bubble.
    """
    is_dark = False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        is_dark = (val == 0)
    except Exception:
        is_dark = False

    if is_dark:
        return {
            "mode": "dark",
            "bubble_fill": "#18181b",      # Deep dark slate/zinc
            "outline": "#38bdf8",          # Sky-blue contrasting comic outline
            "text": "#f4f4f5",             # Clean light text
            "title": "#38bdf8",            # Identity accent
            "tag": "#94a3b8",              # Muted command/intent tag
            "close_btn": "#71717a",        # Muted close icon
            "close_hover": "#f87171",      # Red hover
            "trans_color": "#000001",      # Transparent color key
        }
    else:
        return {
            "mode": "light",
            "bubble_fill": "#ffffff",      # Clean white matching reference image
            "outline": "#18181b",          # Thin dark comic pen outline
            "text": "#18181b",             # Dark legible text
            "title": "#09090b",            # Crisp dark title
            "tag": "#52525b",              # Muted comic tag color
            "close_btn": "#71717a",        # Muted close icon
            "close_hover": "#ef4444",      # Red hover
            "trans_color": "#000001",      # Transparent color key
        }


def compute_comic_bubble_polygon(w, h, r=50, tail_side="bottom", tail_tip_x=80, tail_tip_y=285):
    """
    Computes vertices for a large, horizontally oriented, oval-like comic speech bubble
    with an integrated curved tail pointing toward (tail_tip_x, tail_tip_y).
    Produces a single continuous closed perimeter without seams.
    """
    points = []

    if tail_side == "bottom":
        y1 = 10
        y2 = h - 35
    else:
        y1 = 35
        y2 = h - 10

    x1 = 10
    x2 = w - 10
    r = min(r, (y2 - y1) // 2, (x2 - x1) // 2)

    # 1. Top perimeter (with tail if tail_side == 'top')
    if tail_side == "top":
        for a in range(180, 271, 5):
            rad = math.radians(a)
            points.extend([x1 + r + r * math.cos(rad), y1 + r + r * math.sin(rad)])

        t_base_left = min(x2 - r - 60, max(x1 + r, tail_tip_x - 30))
        t_base_right = t_base_left + 50

        points.extend([t_base_left, y1])
        # Smooth swoop up to tail tip
        for t in (0.3, 0.7, 1.0):
            cx = (1 - t) ** 2 * t_base_left + 2 * (1 - t) * t * (tail_tip_x - 10) + t ** 2 * tail_tip_x
            cy = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * (y1 - (y1 - tail_tip_y) * 0.6) + t ** 2 * tail_tip_y
            points.extend([cx, cy])
        # Smooth swoop back down to right base
        for t in (0.4, 0.8, 1.0):
            cx = (1 - t) ** 2 * tail_tip_x + 2 * (1 - t) * t * (tail_tip_x + 15) + t ** 2 * t_base_right
            cy = (1 - t) ** 2 * tail_tip_y + 2 * (1 - t) * t * (y1 - (y1 - tail_tip_y) * 0.5) + t ** 2 * y1
            points.extend([cx, cy])

        for a in range(270, 361, 5):
            rad = math.radians(a)
            points.extend([x2 - r + r * math.cos(rad), y1 + r + r * math.sin(rad)])
    else:
        for a in range(180, 271, 5):
            rad = math.radians(a)
            points.extend([x1 + r + r * math.cos(rad), y1 + r + r * math.sin(rad)])
        for a in range(270, 361, 5):
            rad = math.radians(a)
            points.extend([x2 - r + r * math.cos(rad), y1 + r + r * math.sin(rad)])

    # 2. Bottom-right arc
    for a in range(0, 91, 5):
        rad = math.radians(a)
        points.extend([x2 - r + r * math.cos(rad), y2 - r + r * math.sin(rad)])

    # 3. Bottom edge (with curved comic tail if tail_side == 'bottom')
    if tail_side == "bottom":
        t_base_right = min(x2 - r, max(x1 + r + 60, tail_tip_x + 35))
        t_base_left = t_base_right - 50

        points.extend([t_base_right, y2])
        # Smooth swoop down to tail tip
        for t in (0.3, 0.7, 1.0):
            cx = (1 - t) ** 2 * t_base_right + 2 * (1 - t) * t * (tail_tip_x + 20) + t ** 2 * tail_tip_x
            cy = (1 - t) ** 2 * y2 + 2 * (1 - t) * t * (y2 + (tail_tip_y - y2) * 0.6) + t ** 2 * tail_tip_y
            points.extend([cx, cy])
        # Smooth swoop back up to left base
        for t in (0.4, 0.8, 1.0):
            cx = (1 - t) ** 2 * tail_tip_x + 2 * (1 - t) * t * (tail_tip_x - 10) + t ** 2 * t_base_left
            cy = (1 - t) ** 2 * tail_tip_y + 2 * (1 - t) * t * (y2 + (tail_tip_y - y2) * 0.5) + t ** 2 * y2
            points.extend([cx, cy])

        for a in range(90, 181, 5):
            rad = math.radians(a)
            points.extend([x1 + r + r * math.cos(rad), y2 - r + r * math.sin(rad)])
    else:
        for a in range(90, 181, 5):
            rad = math.radians(a)
            points.extend([x1 + r + r * math.cos(rad), y2 - r + r * math.sin(rad)])

    return points


def compute_bubble_polygon(*args, **kwargs):
    """
    Backward-compatibility wrapper for compute_comic_bubble_polygon.
    Supports both modern (w, h, ...) and legacy (x1, y1, x2, y2, ...) calls.
    """
    if len(args) >= 4:
        x1, y1, x2, y2 = args[:4]
        w = max(x2, x1 + 100)
        h = max(y2, y1 + 60)
        tail_pos = kwargs.get("tail_pos", args[5] if len(args) > 5 else "bottom-left")
        tail_side = "top" if "top" in str(tail_pos) else "bottom"
        r = kwargs.get("r", args[4] if len(args) > 4 else 50)
        tail_tip_x = kwargs.get("tail_tip_x", 80)
        tail_tip_y = kwargs.get("tail_tip_y", h + 15 if tail_side == "bottom" else 5)
        return compute_comic_bubble_polygon(w, h, r=r, tail_side=tail_side, tail_tip_x=tail_tip_x, tail_tip_y=tail_tip_y)
    return compute_comic_bubble_polygon(*args, **kwargs)


class FloatingBubbleWindow:
    """
    Clean, oval-shaped comic speech-bubble interface for Kya-Ray matching the reference design.

    Key characteristics:
    1. Large horizontally oriented oval-like speech bubble with integrated curved tail.
    2. Follows OS light/dark theme (crisp white in light mode, deep dark in dark mode).
    3. Seamless content layout: no rectangular header bar, no boxed region, no scrollbar.
    4. Adaptive tail orientation pointing toward the selected text/cursor.
    5. Fully transparent desktop background outside the bubble silhouette.
    6. Maintained thread-safety via ui_queue and global hotkey.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Kya-Ray")

        # Dimensions of the horizontal oval comic bubble
        self.width = 480
        self.height = 270

        # Current tail orientation and tip position
        self.tail_side = "bottom"
        self.tail_tip_x = 80
        self.tail_tip_y = self.height - 5

        # Enable borderless floating window and topmost pinning
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        # Detect operating system theme
        self.theme = get_system_theme()

        # Isolated Windows transparent color-key setup
        self.trans_color = self.theme["trans_color"]
        try:
            self.root.attributes("-transparentcolor", self.trans_color)
            self.root.configure(bg=self.trans_color)
        except Exception:
            self.trans_color = self.theme["bubble_fill"]
            self.root.configure(bg=self.trans_color)

        # Variables to track window dragging
        self._drag_start_x = 0
        self._drag_start_y = 0

        # Canvas drawing the rounded comic speech-bubble silhouette and tail
        self.canvas = tk.Canvas(
            root,
            width=self.width,
            height=self.height,
            bg=self.trans_color,
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Draw the comic speech bubble polygon (seamless stroke and solid fill)
        bubble_pts = compute_comic_bubble_polygon(
            self.width,
            self.height,
            r=50,
            tail_side=self.tail_side,
            tail_tip_x=self.tail_tip_x,
            tail_tip_y=self.tail_tip_y,
        )
        self.bubble_polygon = self.canvas.create_polygon(
            bubble_pts,
            fill=self.theme["bubble_fill"],
            outline=self.theme["outline"],
            width=2,
        )

        # Content container frame embedded inside the bubble body
        self.content_frame = tk.Frame(self.canvas, bg=self.theme["bubble_fill"])
        self.content_window_y = 18 if self.tail_side == "bottom" else 42
        self.content_window = self.canvas.create_window(
            (35, self.content_window_y),
            window=self.content_frame,
            anchor=tk.NW,
            width=self.width - 70,
            height=self.height - 62,
        )

        # ----------------------------------------------------------------------
        # Top Row: Kya-Ray identity, inferred intent tag, and clean close button
        # ----------------------------------------------------------------------
        self.header_frame = tk.Frame(self.content_frame, bg=self.theme["bubble_fill"])
        self.header_frame.pack(fill=tk.X, pady=(0, 2))

        # Comic identity / intent label (e.g., "---------- $kya-ray -explain ----------")
        self.header_status = tk.Label(
            self.header_frame,
            text="---------- $kya-ray -explain ----------",
            font=("Segoe UI", 9),
            fg=self.theme["tag"],
            bg=self.theme["bubble_fill"],
        )
        self.header_status.pack(side=tk.LEFT)

        # Backward compatibility alias
        self.title_label = self.header_status
        self.footer_hint = self.header_status

        # Minimalist close icon ('✕')
        self.close_x_btn = tk.Label(
            self.header_frame,
            text=" ✕ ",
            font=("Segoe UI", 9, "bold"),
            fg=self.theme["close_btn"],
            bg=self.theme["bubble_fill"],
            cursor="hand2",
        )
        self.close_x_btn.pack(side=tk.RIGHT)
        self.close_x_btn.bind("<Button-1>", lambda e: self.hide_window())
        self.close_x_btn.bind("<Enter>", lambda e: self.close_x_btn.config(fg=self.theme["close_hover"]))
        self.close_x_btn.bind("<Leave>", lambda e: self.close_x_btn.config(fg=self.theme["close_btn"]))

        # Backward compatibility alias
        self.dismiss_btn = self.close_x_btn

        # ----------------------------------------------------------------------
        # Selection Headline: short concept/snippet in bold (like 'return')
        # ----------------------------------------------------------------------
        self.sel_label = tk.Label(
            self.content_frame,
            text="",
            font=("Segoe UI", 11, "bold"),
            fg=self.theme["title"],
            bg=self.theme["bubble_fill"],
            anchor="w",
        )
        self.sel_label.pack(fill=tk.X, pady=(4, 2))

        # ----------------------------------------------------------------------
        # Response Text: borderless, seamless text display with smooth wrapping
        # ----------------------------------------------------------------------
        self.text_area = tk.Text(
            self.content_frame,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            bg=self.theme["bubble_fill"],
            fg=self.theme["text"],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            spacing1=2,
            spacing3=2,
        )
        self.text_area.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.text_area.insert(
            tk.END,
            "Select text in any window and press Ctrl + Shift + J.\n\n"
            "Kya-Ray will explain, summarize, or inspect code in this comic speech bubble.",
        )
        self.text_area.config(state=tk.DISABLED)

        # Allow mouse-wheel scrolling for longer responses without displaying a scrollbar
        for widget in (self.text_area, self.content_frame, self.canvas):
            widget.bind(
                "<MouseWheel>",
                lambda e: self.text_area.yview_scroll(int(-1 * (e.delta / 120)), "units")
            )

        # Bind mouse drag events to the canvas and non-interactive regions
        for widget in (self.canvas, self.content_frame, self.header_frame, self.header_status, self.sel_label):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)

        # Bind Esc key to cleanly exit the application
        self.root.bind("<Escape>", lambda e: self.on_exit())

        # Position bubble initially
        self.position_bubble()

        # Start checking the queue for events sent from background threads
        self.check_queue()

    def start_drag(self, event):
        """Records initial pointer offset when user starts dragging the bubble."""
        self._drag_start_x = event.x_root - self.root.winfo_x()
        self._drag_start_y = event.y_root - self.root.winfo_y()

    # Aliases for drag handlers
    _on_drag_start = start_drag

    def do_drag(self, event):
        """Moves the window in real-time as the user drags with mouse button held."""
        new_x = event.x_root - self._drag_start_x
        new_y = event.y_root - self._drag_start_y
        self.root.geometry(f"+{new_x}+{new_y}")

    _on_drag_motion = do_drag

    def position_bubble(self, cursor_x=None, cursor_y=None):
        """
        Positions the speech bubble close to the selected text/cursor and adapts
        tail orientation and direction to point directly toward the selection.
        """
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        if cursor_x is not None and cursor_y is not None:
            mx, my = cursor_x, cursor_y
        else:
            mouse_pos = get_mouse_position()
            if mouse_pos:
                mx, my = mouse_pos
            else:
                mx, my = screen_w // 2, screen_h // 2

        # Primary placement: float ABOVE the selected text (matching reference image)
        ideal_y = my - self.height - 12
        ideal_x = mx - 80

        # Adaptive tail orientation: if near screen top edge, place BELOW selection
        if ideal_y < 15:
            target_y = my + 25
            self.tail_side = "top"
            self.tail_tip_y = 5
        else:
            target_y = ideal_y
            self.tail_side = "bottom"
            self.tail_tip_y = self.height - 5

        # Clamp target coordinates to keep bubble completely within visible screen
        target_x = max(15, min(ideal_x, screen_w - self.width - 15))
        target_y = max(15, min(target_y, screen_h - self.height - 45))

        # Compute tail tip X pointing directly toward the mouse cursor
        rel_cursor_x = mx - target_x
        self.tail_tip_x = max(65, min(rel_cursor_x, self.width - 65))

        self.root.geometry(f"{self.width}x{self.height}+{target_x}+{target_y}")

        # Update the canvas speech-bubble polygon to match the active tail side & tip
        bubble_pts = compute_comic_bubble_polygon(
            self.width,
            self.height,
            r=50,
            tail_side=self.tail_side,
            tail_tip_x=self.tail_tip_x,
            tail_tip_y=self.tail_tip_y,
        )
        self.canvas.coords(self.bubble_polygon, *bubble_pts)

        # Adjust content frame vertical position based on tail orientation
        content_y = 18 if self.tail_side == "bottom" else 42
        self.canvas.coords(self.content_window, 35, content_y)

    def _bring_to_front(self):
        """
        Ensures the floating bubble is visible and stays permanently pinned above
        normal application windows (including VS Code).
        """
        self.root.deiconify()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()

    def show_generating(self, selected_text, intent="-explain"):
        """Displays generating state while Ollama processes the text."""
        self.position_bubble()

        intent_tag = intent if intent else "-explain"
        self.header_status.config(text=f"---------- $kya-ray {intent_tag} ----------")

        raw_preview = selected_text.strip()
        first_line = raw_preview.splitlines()[0].strip() if raw_preview.splitlines() else raw_preview
        if len(first_line) <= 45:
            headline = f"'{first_line}'"
        else:
            headline = f"'{first_line[:42]}...'"
        self.sel_label.config(text=headline)

        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(tk.END, f"Thinking with local AI ({OLLAMA_MODEL})...")
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

    def show_explanation(self, selected_text, explanation, run_id=None, intent="-explain"):
        """Displays the AI-generated response directly in the comic speech bubble."""
        intent_tag = intent if intent else "-explain"
        self.header_status.config(text=f"---------- $kya-ray {intent_tag} ----------")

        raw_preview = selected_text.strip()
        first_line = raw_preview.splitlines()[0].strip() if raw_preview.splitlines() else raw_preview
        if len(first_line) <= 45:
            headline = f"'{first_line}'"
        else:
            headline = f"'{first_line[:42]}...'"
        self.sel_label.config(text=headline)

        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(tk.END, explanation.strip())
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

        # Flush pending widget redraw and geometry calculations synchronously
        self.root.update_idletasks()

        if run_id is not None:
            emit_profile_event("answer_displayed", run_id)

    def show_error(self, selected_text, error_message):
        """Displays error details if Ollama inference fails."""
        self.header_status.config(text="---------- $kya-ray [error] ----------")

        raw_preview = selected_text.strip()
        first_line = raw_preview.splitlines()[0].strip() if raw_preview.splitlines() else raw_preview
        if len(first_line) <= 45:
            headline = f"'{first_line}'"
        else:
            headline = f"'{first_line[:42]}...'"
        self.sel_label.config(text=headline)

        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(tk.END, f"Could not generate an answer:\n\n{error_message}")
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

    def show_no_selection(self):
        """Displays notice when user triggered the shortcut with nothing selected."""
        self.position_bubble()
        self.header_status.config(text="---------- $kya-ray ----------")
        self.sel_label.config(text="No Selection")

        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(
            tk.END,
            "No text was selected.\n\n"
            "Please highlight some text in any window and press Ctrl + Shift + J again."
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
                    intent = payload.get("intent", "-explain") if isinstance(payload, dict) else "-explain"
                    self.show_generating(text, intent=intent)
                elif action == "explanation_ready":
                    run_id = payload.get("run_id") if isinstance(payload, dict) else None
                    intent = payload.get("intent", "-explain") if isinstance(payload, dict) else "-explain"
                    self.show_explanation(payload["text"], payload["explanation"], run_id=run_id, intent=intent)
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

    inferred_intent = infer_intent(captured_text)
    print("Captured text:", flush=True)
    print(captured_text, flush=True)
    print(f"Inferred intent: {inferred_intent}", flush=True)
    print("------------------------------------------", flush=True)
    print(f"Requesting AI response from Ollama ({OLLAMA_MODEL}) [{inferred_intent}]...", flush=True)

    # Immediately pop up the floating bubble showing 'Thinking...'
    ui_queue.put(("generating", {"text": captured_text, "run_id": run_id, "intent": inferred_intent}))

    # Perform Ollama inference in this background thread
    if run_id is not None:
        emit_profile_event("ollama_request_started", run_id)
    res = request_ai_explanation(captured_text, intent=inferred_intent)
    success, result, metrics = res[0], res[1], res[2]
    intent = getattr(res, "intent", inferred_intent)

    if run_id is not None:
        emit_profile_event(
            "ollama_response_received",
            run_id,
            error=None if success else "ollama_error",
            metrics=metrics if success else None,
        )

    if success:
        print(f"[{intent}] Response generated successfully:", flush=True)
        print(result, flush=True)
        print("------------------------------------------\n", flush=True)
        if run_id is not None:
            emit_profile_event("ui_update_queued", run_id)
        ui_queue.put(("explanation_ready", {
            "text": captured_text,
            "explanation": result,
            "run_id": run_id,
            "intent": intent,
        }))
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