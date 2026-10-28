import ast
import ctypes
from ctypes import wintypes
import difflib
import json
import math
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import scrolledtext
import urllib.error
import urllib.request
import pyperclip
from pynput import keyboard
import os
import sys

# Ensure logs directory and safe stdout/stderr for windowed/compiled mode
def setup_safe_logging():
    appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    log_dir = os.path.join(appdata, "Kya-Ray")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "kya-ray.log")
    except Exception:
        log_file = None

    class SafeOutput:
        def __init__(self, original_stream, log_path):
            self.original = original_stream
            self.log_path = log_path

        def write(self, text):
            if self.original:
                try:
                    self.original.write(text)
                except Exception:
                    pass
            if self.log_path and text and text.strip():
                try:
                    with open(self.log_path, "a", encoding="utf-8") as f:
                        f.write(text)
                        if not text.endswith("\n"):
                            f.write("\n")
                except Exception:
                    pass

        def flush(self):
            if self.original:
                try:
                    self.original.flush()
                except Exception:
                    pass

    # Redirect stdout and stderr if running windowed without console
    if sys.stdout is None or not hasattr(sys.stdout, "write"):
        sys.stdout = SafeOutput(None, log_file)
    else:
        sys.stdout = SafeOutput(sys.stdout, log_file)

    if sys.stderr is None or not hasattr(sys.stderr, "write"):
        sys.stderr = SafeOutput(None, log_file)
    else:
        sys.stderr = SafeOutput(sys.stderr, log_file)

# ==============================================================================
# Configuration & Constants
# ==============================================================================

# Ollama local API settings
OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3.2:1b"
REQUEST_TIMEOUT_SECONDS = 30

# Sets of modifier keys to track (supports both left and right keys)
CTRL_KEYS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
ALT_KEYS = {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}
if hasattr(keyboard.Key, "alt_gr"):
    ALT_KEYS.add(keyboard.Key.alt_gr)
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
    "dotnet", "find", "apt", "brew", "deno", "rustc", "gcc", "tar", "sed",
    "awk", "ps", "kill", "rm", "cp", "mv",
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

# Curated set of popular standard library and PyPI packages for deterministic typo detection
POPULAR_PYTHON_MODULES = {
    # Python Standard Library
    "sys", "os", "math", "json", "re", "time", "datetime", "typing", "collections",
    "itertools", "functools", "pathlib", "subprocess", "threading", "multiprocessing",
    "asyncio", "unittest", "logging", "urllib", "socket", "http", "sqlite3", "csv",
    "hashlib", "random", "io", "copy", "shutil", "tempfile", "glob", "pickle",
    "struct", "ctypes", "inspect", "ast", "dis", "pdb", "traceback", "gc",
    "contextlib", "dataclasses", "enum", "abc", "queue", "concurrent", "signal",
    "decimal", "fractions", "statistics", "difflib", "textwrap", "unicodedata",
    "email", "html", "xml", "zipfile", "tarfile", "gzip", "bz2", "lzma", "venv",
    "shlex", "base64", "secrets", "uuid", "platform",
    # Popular Third-Party Packages
    "pandas", "numpy", "scipy", "matplotlib", "seaborn", "requests", "httpx",
    "flask", "django", "fastapi", "uvicorn", "pydantic", "sqlalchemy", "pytest",
    "torch", "torchvision", "torchaudio", "tensorflow", "keras", "sklearn",
    "scikit-learn", "cv2", "pillow", "PIL", "yaml", "jinja2", "click", "rich",
    "celery", "redis", "pika", "boto3", "botocore", "google", "openai",
    "anthropic", "transformers", "datasets", "huggingface_hub", "polars",
    "pyarrow", "playwright", "selenium", "beautifulsoup4", "bs4", "scrapy",
    "networkx", "sympy", "tqdm", "pytz", "psutil", "alembic", "gevent", "wheel",
    "setuptools", "dotenv", "watchdog", "paramiko", "cryptography", "pyperclip",
    "pynput", "tkinter",
}

# Creation prompt trigger verbs and prefixes
CREATE_TRIGGERS = (
    "write a", "write an", "write me a", "write me an", "write me",
    "create a", "create an", "create me a", "create me an", "create me",
    "generate a", "generate an", "draft a", "draft an", "draft me a",
    "make a list of", "build a", "build an", "compose a", "compose an",
    "implement a", "implement an", "template for", "boilerplate for",
    "give me a", "give me an", "give me", "come up with", "suggest a",
    "suggest an", "suggest", "rewrite a", "rewrite an", "rewrite this",
    "rewrite as", "rewrite",
)

# Prefixes identifying explicit explanatory questions
EXPLAIN_QUESTION_PREFIXES = (
    "explain ", "explain how to ", "explain why ", "explain what ",
    "what is ", "what are ", "what was ", "what were ",
    "why is ", "why are ", "why do ", "why does ", "why did ",
    "how do ", "how does ", "how can ", "how to ",
    "tell me about ", "define ",
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
        "Do not assume the input contains an error. If there is a clear, obvious syntax error or misspelled identifier, "
        "identify the typo and state the correction separately. "
        "Do not silently normalize misspelled imports as if they were valid packages. "
        "If the syntax is valid or no obvious error is found, explain the valid behavior without inventing errors or changes. "
        "The input is only provided as text: do not claim it was executed or run, and never invent command execution results, error messages, or reasons for failure. "
        "Finish cleanly without trailing off or starting an incomplete sentence."
    ),
    "-create": (
        "Fulfill the following writing or drafting request directly and concisely. "
        "Treat requests as legitimate without deception. "
        "Generate the requested text directly without conversational preamble, finishing cleanly without trailing off."
    ),
}


TYPED_DECLARATION_PREFIXES = (
    "int ", "float ", "double ", "char ", "bool ", "boolean ",
    "void ", "val ", "auto ", "mut ", "short ", "long ", "byte ",
    "uint ", "size_t ",
)


def is_typed_declaration_or_code_line(line):
    """
    Checks if a single stripped line represents a typed declaration or code statement.
    Anchored to line start to avoid false matches on English prose (e.g. 'international', 'integral').
    """
    stripped = line.strip()
    if not stripped:
        return False

    for prefix in TYPED_DECLARATION_PREFIXES:
        if stripped.startswith(prefix):
            remainder = stripped[len(prefix):].strip()
            if not remainder:
                return False
            tokens = remainder.split()
            first_ident = tokens[0].split("(")[0].rstrip(";,:=")
            if first_ident.isidentifier():
                if "=" in remainder or "(" in remainder or remainder.endswith(";") or len(tokens) == 1:
                    return True

    return False


def is_assignment_line(line):
    """Checks if a line is a code assignment (e.g., 'sum = a + b', 'x = 42')."""
    stripped = line.strip().rstrip(";")
    if "=" not in stripped or "==" in stripped or "!=" in stripped or "<=" in stripped or ">=" in stripped:
        return False
    parts = stripped.split("=", 1)
    lhs = parts[0].strip()
    if lhs and all(part.isidentifier() for part in lhs.split(".")):
        rhs = parts[1].strip()
        if rhs and not rhs.endswith((".", "!", "?")):
            return True
    return False


def is_single_line_code_assignment_or_call(text):
    """
    Checks if a single-line text represents a code assignment or instantiation,
    such as 'app = FastAPI()' or 'client = MongoClient("localhost")',
    distinguishing it from mathematical formulas like 'y = mx + b' or 'f(x) = x^2'.
    """
    stripped = text.strip().rstrip(";")
    if "\n" in stripped or "=" not in stripped:
        return False
    if "==" in stripped or "!=" in stripped or "<=" in stripped or ">=" in stripped:
        return False

    parts = stripped.split("=", 1)
    lhs = parts[0].strip()
    rhs = parts[1].strip()

    if not (lhs.isidentifier() or all(part.isidentifier() for part in lhs.split("."))):
        return False

    if "(" in rhs and rhs.endswith(")"):
        func_token = rhs.split("(", 1)[0].strip()
        if func_token.isidentifier() or all(part.isidentifier() for part in func_token.split(".")):
            return True

    return False


def strip_surrounding_quotes(text):
    """
    Removes surrounding outer matching quotes from generated responses
    if the entire response is enclosed in quotes, without removing internal quotes
    or markdown backticks.
    """
    if not text:
        return text
    stripped = text.strip()
    if len(stripped) >= 2:
        if (stripped.startswith('"') and stripped.endswith('"') and stripped.count('"') == 2) or \
           (stripped.startswith("'") and stripped.endswith("'") and stripped.count("'") == 2):
            return stripped[1:-1].strip()
        if stripped.startswith('“') and stripped.endswith('”'):
            return stripped[1:-1].strip()
    return stripped


NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


CREATE_NOUNS_PATTERN = r"(?:reasons?|options?|ideas?|examples?|lines?|items?|ways?|points?|alternatives?|variations?|titles?|names?|prompts?|questions?|tips?|habits?|snacks?|quotes?|jokes?|messages?|replies?|sentences?|paragraphs?|words?)"


def detect_create_quantity(text):
    """
    Determines requested quantity for creation prompts.
    Returns (quantity: int | None, is_explicit_multiple: bool):
      - Explicit quantity (e.g., '3 reasons', '5 healthy snacks') -> (N, True)
      - Plural list or collection (e.g., 'a list of', 'a few', 'several') -> (None, True)
      - Singular request (e.g., 'a cute pickup line', 'an email', default) -> (1, False)
    """
    raw = (text or "").strip().lower()

    # Check for digit quantities with optional adjective (e.g. "3 pickup lines", "5 healthy snacks", "10 examples")
    digit_match = re.search(r'\b(\d+)\s+(?:[a-z_\-]+\s+)?' + CREATE_NOUNS_PATTERN + r'\b', raw)
    if digit_match:
        return int(digit_match.group(1)), True

    # Check for digit alone if preceded by command verbs (e.g. "give me 3", "list of 5")
    digit_solo = re.search(r'\b(?:give me|list of|top|create|write)\s+(\d+)\b', raw)
    if digit_solo:
        return int(digit_solo.group(1)), True

    # Check for number words with optional adjective (e.g. "three reasons", "two cute pickup lines", "five snacks")
    word_pattern = r'\b(' + '|'.join(NUMBER_WORDS.keys()) + r')\s+(?:[a-z_\-]+\s+)?' + CREATE_NOUNS_PATTERN + r'\b'
    word_match = re.search(word_pattern, raw)
    if word_match:
        qty = NUMBER_WORDS[word_match.group(1)]
        return qty, (qty > 1)

    word_solo = re.search(r'\b(?:give me|list of|top|create|write)\s+(' + '|'.join(NUMBER_WORDS.keys()) + r')\b', raw)
    if word_solo:
        qty = NUMBER_WORDS[word_solo.group(1)]
        return qty, (qty > 1)

    # Check for general plural or list indicators without specific count
    if any(phrase in raw for phrase in ("a list of", "make a list", "give me a few", "give me some", "options for", "ideas for", "several", "multiple")):
        return None, True

    return 1, False


def strip_conversational_preamble(text):
    """
    Removes common chatty conversational greetings and lead-in preambles
    specifically from creative generation outputs (e.g. 'I\'d be happy to provide...',
    'Here is a cute pickup line:').
    Does not alter genuine content if no preamble is present.
    """
    if not text:
        return text

    stripped = text.strip()

    pats = [
        r"^(?:I'd|I would) be happy to (?:provide|suggest|give|write|help you with)[^.\n]*\.\s*(?:How about:\s*|Here(?:'s| is)[^:\n]*:\s*)?",
        r"^(?:Sure|Certainly|Of course)[!.,]?\s*(?:Here(?:'s| is)[^:\n]*:?\s*)?",
        r"^(?:Here(?:'s| is) (?:a|an|one|the) [^:\n]*:\s*)",
        r"^(?:How about|What about):\s*",
    ]
    for pat in pats:
        m = re.match(pat, stripped, flags=re.IGNORECASE)
        if m:
            remainder = stripped[m.end():].strip()
            if remainder:
                stripped = remainder

    return stripped


def extract_single_creation_output(text):
    """
    For simple, singular creation requests, ensures only one finished output is returned,
    trimming redundant subsequent options or numbered lists.
    """
    if not text:
        return text
    stripped = text.strip()

    # If format is "1. First line\n2. Second line..."
    lines = stripped.splitlines()
    if lines and (lines[0].startswith("1. ") or lines[0].startswith("1) ")):
        first_item_lines = [lines[0][3:].strip()]
        for line in lines[1:]:
            if re.match(r"^\d+[\.\)]\s+", line.strip()):
                break
            if line.strip():
                first_item_lines.append(line.strip())
            else:
                break
        return " ".join(first_item_lines)

    # If there are multiple paragraphs and paragraph 2 starts with "I'd also suggest" or "Another option"
    paras = [p.strip() for p in stripped.split("\n\n") if p.strip()]
    if len(paras) > 1 and any(paras[1].lower().startswith(p) for p in ("i'd also", "another option", "or you could say", "here is another", "second")):
        return paras[0]

    return stripped


def check_code_diagnostics(text):
    """
    Performs deterministic static code analysis on a given text:
    1. Checks if the snippet can be parsed as Python via ast.parse.
    2. Identifies import statements and checks whether imported modules look like
       misspelled typos of well-known Python packages (e.g. 'panadas' -> 'pandas',
       'numppy' -> 'numpy').
    3. Guarantees unfamiliar modules without close matches are NOT flagged.
    4. Distinguishes Python code from shell commands and non-code prose/math.

    Returns dict:
      {
          "is_python": bool,
          "is_valid_python": bool,
          "syntax_error": str | None,
          "has_typo": bool,
          "typos": list of tuple (misspelled_name, suggested_match),
          "diagnostics_note": str | None,
      }
    """
    raw = (text or "").strip()
    result = {
        "is_python": False,
        "is_valid_python": False,
        "syntax_error": None,
        "has_typo": False,
        "typos": [],
        "diagnostics_note": None,
    }
    if not raw:
        return result

    # Check if text is a shell command (e.g., starts with CLI command name)
    first_token = raw.split()[0].lower() if raw.split() else ""
    if first_token in ("$", ">", "#") and len(raw.split()) > 1:
        first_token = raw.split()[1].lower()
    if first_token in CLI_COMMANDS:
        return result

    # Check for pure math equations that aren't programming code
    if any(raw.startswith(m) for m in ("y = mx + b", "f(x) =", "E = mc^2", "A = pi * r^2")):
        return result

    try:
        tree = ast.parse(raw)
        result["is_python"] = True
        result["is_valid_python"] = True

        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    imported_modules.append(root_mod)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0]
                    imported_modules.append(root_mod)

        typos = []
        for mod in imported_modules:
            mod_lower = mod.lower()
            if mod_lower not in POPULAR_PYTHON_MODULES:
                matches = difflib.get_close_matches(mod_lower, POPULAR_PYTHON_MODULES, n=1, cutoff=0.75)
                if matches and matches[0] != mod_lower:
                    typos.append((mod, matches[0]))

        if typos:
            result["has_typo"] = True
            result["typos"] = typos
            typo_notes = [f"'{t[0]}' appears to be a typo for '{t[1]}'" for t in typos]
            result["diagnostics_note"] = (
                f"Static check detected likely import typo: {', '.join(typo_notes)}. "
                f"Point out the typo and suggest the correction separately; do not silently normalize it."
            )
        elif imported_modules or any(kw in raw for kw in ("def ", "class ", "async def ", "app = ", "return ", "=")):
            result["diagnostics_note"] = (
                "Static analysis confirms valid Python syntax with NO typos or errors. "
                "Do NOT invent or suggest any typos, corrections, or syntax changes. Explain only the valid behavior."
            )

    except SyntaxError as e:
        if any(kw in raw for kw in ("def ", "class ", "import ", "from ", "return ", "async def ")):
            result["is_python"] = True
            result["is_valid_python"] = False
            result["syntax_error"] = f"SyntaxError at line {e.lineno}: {e.msg}"
            result["diagnostics_note"] = f"Static analysis detected genuine syntax error: {e.msg} at line {e.lineno}."
    except Exception:
        pass

    return result


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

    # 1. Distinguish explicit explanatory questions from generation directives:
    is_explanatory_question = any(lower.startswith(p) for p in EXPLAIN_QUESTION_PREFIXES)

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
        (raw.endswith(";") and ("=" in raw or "(" in raw)) or
        is_single_line_code_assignment_or_call(raw)
    )
    if has_code_symbols:
        return "-code"

    # C. Explicit code declarations and typed statements
    has_explicit_code_def = any(
        line.strip().startswith(("def ", "class ", "function ", "async def ", "public class ", "import ", "interface "))
        or (line.strip().startswith("from ") and " import " in line)
        or is_typed_declaration_or_code_line(line)
        for line in raw.splitlines()
    )
    if has_explicit_code_def:
        return "-code"

    # D. Multiline code block signals (>= 2 lines with assignments or typed statements)
    raw_lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if len(raw_lines) >= 2:
        code_signal_lines = sum(
            1 for line in raw_lines
            if is_typed_declaration_or_code_line(line) or is_assignment_line(line)
        )
        if code_signal_lines >= 2:
            return "-code"

    # 3. Detect -create: explicit generation/creation directives (when not an explanatory question)
    if not is_explanatory_question:
        for trigger in CREATE_TRIGGERS:
            if lower.startswith(trigger) or (word_count < 30 and (f" {trigger} " in f" {lower} " or lower.startswith(trigger))):
                return "-create"

    # 4. Detect -summarize:
    # Substantial natural language prose (>= 50 words, or multiple paragraphs / bulleted items >= 20 words)
    has_bullets = any(line.strip().startswith(("-", "*", "•")) for line in raw.splitlines())
    has_multiple_paragraphs = len([p for p in raw.split("\n\n") if p.strip()]) >= 2
    if word_count >= 50 or ((has_multiple_paragraphs or has_bullets) and word_count >= 20):
        return "-summarize"

    # 5. Short code snippets and terminal commands (< 50 words)
    # A. Common terminal commands (checked on short command lines)
    first_token = first_line.split()[0] if first_line.split() else ""
    if first_token in ("$", ">", "#") and len(first_line.split()) > 1:
        first_token = first_line.split()[1]
    if first_token in CLI_COMMANDS and word_count < 30:
        return "-code"

    # B. Language keywords / syntax constructs in short snippets
    if any(kw in raw for kw in CODE_KEYWORDS) or ("from " in raw and " import " in raw):
        return "-code"

    # 6. Default to -explain (concepts, phrases, single words, definitions)
    return "-explain"


def build_intent_prompt(text, intent):
    """Formats the intent-specific instruction prefix and user text."""
    prefix = INTENT_INSTRUCTIONS.get(intent, INTENT_INSTRUCTIONS["-explain"])

    extra_guidance = ""
    if intent == "-code":
        diag = check_code_diagnostics(text)
        if diag.get("diagnostics_note"):
            extra_guidance = f"\n{diag['diagnostics_note']}"
    elif intent == "-create":
        qty, is_multiple = detect_create_quantity(text)
        if not is_multiple and qty == 1:
            extra_guidance = (
                "\nProvide exactly ONE finished output directly without multiple options or alternatives. "
                "Do not include conversational preamble. "
                "Output only the created text, finishing cleanly with terminal punctuation."
            )
        elif is_multiple and qty is not None:
            extra_guidance = (
                f"\nProvide exactly {qty} options directly, respecting the requested quantity. "
                "Do not include conversational preamble. "
                "Output only the requested items directly, finishing cleanly."
            )
        else:
            extra_guidance = (
                "\nProvide the requested content directly and concisely. "
                "Do not include conversational preamble. "
                "Output only the requested items directly, finishing cleanly."
            )

    return f"{prefix}{extra_guidance}\n\n\"{text.strip()}\""


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

def check_ollama_prerequisites():
    """
    Non-blocking check for Ollama API availability and the required model.
    Does NOT download models automatically. Returns (status, message).
    """
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                found = any(OLLAMA_MODEL in m for m in models)
                if found:
                    return "ready", f"Ollama is running with {OLLAMA_MODEL}."
                return "model_missing", f"Ollama is running, but model '{OLLAMA_MODEL}' was not found.\n\nPlease run 'ollama pull {OLLAMA_MODEL}' in your terminal."
    except urllib.error.URLError:
        return "offline", "Could not connect to Ollama (http://127.0.0.1:11434).\n\nPlease launch the Ollama desktop application."
    except Exception as e:
        return "offline", f"Ollama check failed: {e}"
    return "offline", "Ollama is not reachable."


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
        "think": False,
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
                if intent == "-create":
                    raw_explanation = strip_conversational_preamble(raw_explanation)
                    qty, is_multiple = detect_create_quantity(text)
                    if not is_multiple and qty == 1:
                        raw_explanation = extract_single_creation_output(raw_explanation)
                cleaned_quotes = strip_surrounding_quotes(raw_explanation)
                explanation = clean_truncated_sentence(cleaned_quotes)
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
# GUI: Minimal Floating Panel (Tkinter)
# ==============================================================================

INTENT_DISPLAY_LABELS = {
    "-explain": "Explain",
    "-summarize": "Summary",
    "-code": "Code",
    "-create": "Create",
}


def get_system_theme():
    """
    Detects Windows OS light/dark theme preference via registry.
    Returns a dictionary of cohesive colors for the minimal floating panel.
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
            "outline": "#334155",          # Restrained subtle outline
            "text": "#f4f4f5",             # Clean light text
            "title": "#38bdf8",            # Identity accent
            "tag": "#94a3b8",              # Muted command/intent tag
            "code_bg": "#27272a",          # Zinc-800 for code blocks
            "code_inline_bg": "#27272a",   # Zinc-800 for inline code
            "close_btn": "#71717a",        # Muted controls
            "close_hover": "#38bdf8",      # Accent hover
            "trans_color": "#000001",      # Transparent color key
        }
    else:
        return {
            "mode": "light",
            "bubble_fill": "#ffffff",      # Clean white background
            "outline": "#e2e8f0",          # Subtle border (slate-200)
            "text": "#0f172a",             # Dark, high-contrast body text (slate-900)
            "title": "#0284c7",            # Restrained blue accent (sky-600)
            "tag": "#64748b",              # Muted slate-500
            "code_bg": "#f8fafc",          # Very soft slate-50 background for code blocks
            "code_inline_bg": "#f1f5f9",   # Soft slate-100 background for inline code
            "close_btn": "#64748b",        # Slate-500
            "close_hover": "#0284c7",      # Blue accent on hover
            "trans_color": "#000001",      # Transparent color key
        }


def render_formatted_response(text_widget, text, theme=None):
    """
    Renders AI response into Tkinter Text widget with structured tags:
    - Fenced code blocks (``` ... ```) in Consolas with subtle background
    - Bulleted and numbered lists with left indentation
    - Inline backtick code snippets
    - Paragraph breaks with natural spacing
    - Strips unnecessary outer quotation marks
    """
    text_widget.config(state=tk.NORMAL)
    text_widget.delete("1.0", tk.END)

    cleaned = strip_surrounding_quotes(text or "")
    if not cleaned:
        text_widget.config(state=tk.DISABLED)
        return

    lines = cleaned.splitlines()
    in_code_block = False
    code_block_lines = []

    for idx, line in enumerate(lines):
        stripped_line = line.strip()
        if stripped_line.startswith("```"):
            if in_code_block:
                block_text = "\n".join(code_block_lines) + "\n"
                text_widget.insert(tk.END, block_text, ("code_block",))
                code_block_lines = []
                in_code_block = False
            else:
                in_code_block = True
                code_block_lines = []
            continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        # Check for bullet / list item
        is_bullet = False
        for bullet_prefix in ("- ", "* ", "• "):
            if stripped_line.startswith(bullet_prefix):
                is_bullet = True
                break
        if not is_bullet and re.match(r"^\d+\.\s+", stripped_line):
            is_bullet = True

        line_tag = "bullet" if is_bullet else "body"

        if "`" in line:
            parts = line.split("`")
            for i, part in enumerate(parts):
                if i % 2 == 1:
                    text_widget.insert(tk.END, part, ("code_inline",))
                else:
                    text_widget.insert(tk.END, part, (line_tag,))
        else:
            text_widget.insert(tk.END, line, (line_tag,))

        if idx < len(lines) - 1:
            text_widget.insert(tk.END, "\n")

    if in_code_block and code_block_lines:
        block_text = "\n".join(code_block_lines) + "\n"
        text_widget.insert(tk.END, block_text, ("code_block",))

    text_widget.config(state=tk.DISABLED)


def compute_rounded_panel_polygon(w, h, r=10):
    """
    Computes vertices for a compact, minimal floating panel with subtle rounded corners.
    Produces a single continuous closed perimeter.
    """
    points = []
    x1, y1 = 4, 4
    x2, y2 = w - 4, h - 4
    r = min(r, (y2 - y1) // 2, (x2 - x1) // 2)

    # Top-left arc
    for a in range(180, 271, 10):
        rad = math.radians(a)
        points.extend([x1 + r + r * math.cos(rad), y1 + r + r * math.sin(rad)])
    # Top-right arc
    for a in range(270, 361, 10):
        rad = math.radians(a)
        points.extend([x2 - r + r * math.cos(rad), y1 + r + r * math.sin(rad)])
    # Bottom-right arc
    for a in range(0, 91, 10):
        rad = math.radians(a)
        points.extend([x2 - r + r * math.cos(rad), y2 - r + r * math.sin(rad)])
    # Bottom-left arc
    for a in range(90, 181, 10):
        rad = math.radians(a)
        points.extend([x1 + r + r * math.cos(rad), y2 - r + r * math.sin(rad)])

    return points


def compute_comic_bubble_polygon(w, h, r=50, tail_side="bottom", tail_tip_x=80, tail_tip_y=285):
    """
    Retained for backward compatibility with geometry unit tests.
    Computes vertices for a comic speech bubble silhouette.
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

    if tail_side == "top":
        for a in range(180, 271, 5):
            rad = math.radians(a)
            points.extend([x1 + r + r * math.cos(rad), y1 + r + r * math.sin(rad)])
        t_base_left = min(x2 - r - 60, max(x1 + r, tail_tip_x - 30))
        t_base_right = t_base_left + 50
        points.extend([t_base_left, y1])
        for t in (0.3, 0.7, 1.0):
            cx = (1 - t) ** 2 * t_base_left + 2 * (1 - t) * t * (tail_tip_x - 10) + t ** 2 * tail_tip_x
            cy = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * (y1 - (y1 - tail_tip_y) * 0.6) + t ** 2 * tail_tip_y
            points.extend([cx, cy])
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

    for a in range(0, 91, 5):
        rad = math.radians(a)
        points.extend([x2 - r + r * math.cos(rad), y2 - r + r * math.sin(rad)])

    if tail_side == "bottom":
        t_base_right = min(x2 - r, max(x1 + r + 60, tail_tip_x + 35))
        t_base_left = t_base_right - 50
        points.extend([t_base_right, y2])
        for t in (0.3, 0.7, 1.0):
            cx = (1 - t) ** 2 * t_base_right + 2 * (1 - t) * t * (tail_tip_x + 20) + t ** 2 * tail_tip_x
            cy = (1 - t) ** 2 * y2 + 2 * (1 - t) * t * (y2 + (tail_tip_y - y2) * 0.6) + t ** 2 * tail_tip_y
            points.extend([cx, cy])
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
    Backward-compatibility wrapper for bubble polygon calculations.
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
    Compact, minimal floating panel for Kya-Ray.

    Key characteristics:
    1. Restrained border with subtle rounded corners and clean padding.
    2. Follows OS light/dark theme preference.
    3. The generated answer is the absolute visual focus; selected text is not displayed as quoted input.
    4. Shows subtle intent label (Explain, Summary, Code, or Create).
    5. Minimal controls: top-right close '✕' to dismiss, 'Exit' link for clean shutdown, right-click menu.
    6. Escape dismisses the visible panel without terminating the background process.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Kya-Ray")

        # Dimensions of the compact floating panel
        self.width = 440
        self.height = 190

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

        # Canvas drawing the rounded panel silhouette
        self.canvas = tk.Canvas(
            root,
            width=self.width,
            height=self.height,
            bg=self.trans_color,
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Draw the compact panel polygon (restrained border and solid fill)
        panel_pts = compute_rounded_panel_polygon(self.width, self.height, r=10)
        self.bubble_polygon = self.canvas.create_polygon(
            panel_pts,
            fill=self.theme["bubble_fill"],
            outline=self.theme["outline"],
            width=1.5,
        )

        # Content container frame embedded inside the panel
        self.content_frame = tk.Frame(self.canvas, bg=self.theme["bubble_fill"])
        self.content_window = self.canvas.create_window(
            (14, 10),
            window=self.content_frame,
            anchor=tk.NW,
            width=self.width - 28,
            height=self.height - 20,
        )

        # ----------------------------------------------------------------------
        # Header Row: Subtle intent badge and minimal controls (Exit | ✕)
        # ----------------------------------------------------------------------
        self.header_frame = tk.Frame(self.content_frame, bg=self.theme["bubble_fill"])
        self.header_frame.pack(fill=tk.X, pady=(0, 4))

        # Subtle intent indicator (e.g., "Kya-Ray · Explain")
        self.header_status = tk.Label(
            self.header_frame,
            text="Kya-Ray · Explain",
            font=("Segoe UI", 9, "bold"),
            fg=self.theme["title"],
            bg=self.theme["bubble_fill"],
        )
        self.header_status.pack(side=tk.LEFT)

        # Backward compatibility aliases
        self.title_label = self.header_status
        self.footer_hint = self.header_status

        # Minimal controls container on the right
        self.controls_frame = tk.Frame(self.header_frame, bg=self.theme["bubble_fill"])
        self.controls_frame.pack(side=tk.RIGHT)

        # Small Understated Copy button
        self.copy_btn = tk.Label(
            self.controls_frame,
            text="Copy",
            font=("Segoe UI", 8),
            fg=self.theme["close_btn"],
            bg=self.theme["bubble_fill"],
            cursor="hand2",
        )
        self.copy_btn.pack(side=tk.LEFT, padx=(0, 5))
        self.copy_btn.bind("<Button-1>", lambda e: self.on_copy())
        self.copy_btn.bind("<Enter>", lambda e: self.copy_btn.config(fg=self.theme["close_hover"]))
        self.copy_btn.bind("<Leave>", lambda e: self.copy_btn.config(fg=self.theme["close_btn"]))

        # Subtle separator
        self.sep_label1 = tk.Label(
            self.controls_frame,
            text="|",
            font=("Segoe UI", 8),
            fg=self.theme["close_btn"],
            bg=self.theme["bubble_fill"],
        )
        self.sep_label1.pack(side=tk.LEFT, padx=(0, 5))

        # Discoverable, deliberate Exit button
        self.exit_btn = tk.Label(
            self.controls_frame,
            text="Exit",
            font=("Segoe UI", 8),
            fg=self.theme["close_btn"],
            bg=self.theme["bubble_fill"],
            cursor="hand2",
        )
        self.exit_btn.pack(side=tk.LEFT, padx=(0, 5))
        self.exit_btn.bind("<Button-1>", lambda e: self.on_exit())
        self.exit_btn.bind("<Enter>", lambda e: self.exit_btn.config(fg=self.theme["close_hover"]))
        self.exit_btn.bind("<Leave>", lambda e: self.exit_btn.config(fg=self.theme["close_btn"]))

        # Subtle separator
        self.sep_label2 = tk.Label(
            self.controls_frame,
            text="|",
            font=("Segoe UI", 8),
            fg=self.theme["close_btn"],
            bg=self.theme["bubble_fill"],
        )
        self.sep_label = self.sep_label2  # backward compatibility alias
        self.sep_label2.pack(side=tk.LEFT, padx=(0, 5))

        # Minimal close icon ('✕') to dismiss
        self.close_x_btn = tk.Label(
            self.controls_frame,
            text="✕",
            font=("Segoe UI", 9, "bold"),
            fg=self.theme["close_btn"],
            bg=self.theme["bubble_fill"],
            cursor="hand2",
        )
        self.close_x_btn.pack(side=tk.LEFT)
        self.close_x_btn.bind("<Button-1>", lambda e: self.hide_window())
        self.close_x_btn.bind("<Enter>", lambda e: self.close_x_btn.config(fg=self.theme["close_hover"]))
        self.close_x_btn.bind("<Leave>", lambda e: self.close_x_btn.config(fg=self.theme["close_btn"]))

        # Backward compatibility alias
        self.dismiss_btn = self.close_x_btn

        # Attribute retained for backward-compatibility with tests, but NOT packed
        # (Selected text is context for the model, not displayed as quoted input)
        self.sel_label = tk.Label(
            self.content_frame,
            text="",
            font=("Segoe UI", 9),
            fg=self.theme["tag"],
            bg=self.theme["bubble_fill"],
        )

        # ----------------------------------------------------------------------
        # Response Text: The visual focus of the floating panel
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
            spacing1=1,
            spacing3=1,
        )
        self.text_area.tag_configure("body", font=("Segoe UI", 10), foreground=self.theme["text"], spacing1=2, spacing3=3)
        self.text_area.tag_configure("bold", font=("Segoe UI", 10, "bold"), foreground=self.theme["text"])
        self.text_area.tag_configure("bullet", font=("Segoe UI", 10), foreground=self.theme["text"], lmargin1=16, lmargin2=28, spacing1=2, spacing3=2)
        self.text_area.tag_configure("code_inline", font=("Consolas", 9), foreground=self.theme["text"], background=self.theme.get("code_inline_bg", "#f1f5f9"))
        self.text_area.tag_configure("code_block", font=("Consolas", 9), foreground=self.theme["text"], background=self.theme.get("code_bg", "#f8fafc"), lmargin1=14, lmargin2=14, spacing1=4, spacing3=4)
        self.text_area.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.text_area.insert(
            tk.END,
            "Select text in any window and press Ctrl + Alt + Space.\n\n"
            "Kya-Ray will provide a concise answer directly here.",
        )
        self.text_area.config(state=tk.DISABLED)

        # Right-click context menu for deliberate options
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Dismiss Bubble (Esc)", command=self.hide_window)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Exit Kya-Ray completely", command=self.on_exit)

        def _show_context_menu(event):
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

        # Mouse bindings
        for widget in (self.canvas, self.content_frame, self.header_frame, self.header_status, self.text_area):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)
            widget.bind("<Button-3>", _show_context_menu)
            widget.bind(
                "<MouseWheel>",
                lambda e: self.text_area.yview_scroll(int(-1 * (e.delta / 120)), "units")
            )

        # Bind Esc key on root window to dismiss the bubble (NOT exit the app)
        self.root.bind("<Escape>", lambda e: self.hide_window())

        # Tail attributes for backward compatibility with geometry tests
        self.tail_side = "bottom"
        self.tail_tip_x = 80
        self.tail_tip_y = self.height - 5

        # Position panel initially
        self.position_bubble()

        # Start checking the queue
        self.check_queue()

    def start_drag(self, event):
        """Records initial pointer offset when user starts dragging the panel."""
        self._drag_start_x = event.x_root - self.root.winfo_x()
        self._drag_start_y = event.y_root - self.root.winfo_y()

    _on_drag_start = start_drag

    def do_drag(self, event):
        """Moves the window in real-time as the user drags with mouse button held."""
        new_x = event.x_root - self._drag_start_x
        new_y = event.y_root - self._drag_start_y
        self.root.geometry(f"+{new_x}+{new_y}")

    _on_drag_motion = do_drag

    def position_bubble(self, cursor_x=None, cursor_y=None):
        """Positions the floating panel close to the mouse cursor clamped to screen bounds."""
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

        # Primary placement: float above cursor
        ideal_y = my - self.height - 12
        ideal_x = mx - 40

        if ideal_y < 15:
            target_y = my + 25
            self.tail_side = "top"
            self.tail_tip_y = 5
        else:
            target_y = ideal_y
            self.tail_side = "bottom"
            self.tail_tip_y = self.height - 5

        target_x = max(15, min(ideal_x, screen_w - self.width - 15))
        target_y = max(15, min(target_y, screen_h - self.height - 45))

        self.root.geometry(f"{self.width}x{self.height}+{target_x}+{target_y}")

    def _bring_to_front(self):
        """Ensures the floating panel is visible and stays pinned above other windows."""
        self.root.deiconify()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()

    def on_copy(self):
        """Copies current answer to clipboard with subtle transient confirmation."""
        raw_text = getattr(self, "_current_raw_answer", None)
        if not raw_text:
            raw_text = self.text_area.get("1.0", tk.END).strip()

        if raw_text:
            try:
                pyperclip.copy(raw_text)
                self.copy_btn.config(text="Copied!", fg=self.theme["title"])
                self.root.after(1400, lambda: self.copy_btn.config(text="Copy", fg=self.theme["close_btn"]))
            except Exception as e:
                print(f"[Warning] Failed to copy to clipboard: {e}", flush=True)

    def _resize_panel(self, target_height):
        """Resizes the canvas and polygon to match the target dynamic height."""
        self.height = target_height
        panel_pts = compute_rounded_panel_polygon(self.width, self.height, r=10)
        self.canvas.coords(self.bubble_polygon, *panel_pts)
        self.canvas.itemconfig(self.content_window, height=self.height - 20)
        self.canvas.config(height=self.height)

    def show_generating(self, selected_text, intent="-explain"):
        """Displays generating state while Ollama processes the text."""
        self._resize_panel(190)
        self.position_bubble()
        label = INTENT_DISPLAY_LABELS.get(intent, "Explain")
        self.header_status.config(text=f"Kya-Ray · {label}")

        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(tk.END, f"Thinking with local AI ({OLLAMA_MODEL})...", ("body",))
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

    def show_explanation(self, selected_text, explanation, run_id=None, intent="-explain"):
        """Displays the AI-generated response directly in the minimal floating panel."""
        label = INTENT_DISPLAY_LABELS.get(intent, "Explain")
        self.header_status.config(text=f"Kya-Ray · {label}")
        self._current_raw_answer = explanation.strip()

        # Dynamic height adaptation based on response length (min 170px, max 340px)
        lines = self._current_raw_answer.splitlines()
        line_count = 0
        for l in lines:
            line_count += max(1, len(l) // 44 + 1)
        target_height = max(170, min(340, 70 + line_count * 20))
        self._resize_panel(target_height)
        self.position_bubble()

        render_formatted_response(self.text_area, self._current_raw_answer, theme=self.theme)

        self._bring_to_front()
        self.root.update_idletasks()

        if run_id is not None:
            emit_profile_event("answer_displayed", run_id)

    def show_error(self, selected_text, error_message):
        """Displays error details if Ollama inference fails."""
        self._resize_panel(190)
        self.position_bubble()
        self.header_status.config(text="Kya-Ray · Error")

        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(tk.END, f"Could not generate an answer:\n\n{error_message}", ("body",))
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

    def show_no_selection(self):
        """Displays notice when user triggered the shortcut with nothing selected."""
        self._resize_panel(190)
        self.position_bubble()
        self.header_status.config(text="Kya-Ray · Notice")

        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(
            tk.END,
            "No text was selected.\n\n"
            "Please highlight some text in any window and press Ctrl + Alt + Space.",
            ("body",)
        )
        self.text_area.config(state=tk.DISABLED)

        self._bring_to_front()

    def show_startup_notice(self, status, message):
        """Displays startup prerequisite notice if Ollama or model is unavailable."""
        self._resize_panel(190)
        self.position_bubble()
        self.header_status.config(text="Kya-Ray · Prerequisite Notice")

        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(
            tk.END,
            f"{message}\n\n"
            "Kya-Ray is active in the background. Press Ctrl + Alt + Space once ready.",
            ("body",)
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
        """Hides the panel when dismissed by the user."""
        self.root.withdraw()
        print("Panel dismissed. Press Ctrl + Alt + Space to show it again, or click Exit to quit.", flush=True)

    def on_exit(self):
        """Cleanly terminates the application when exiting."""
        print("\nKya-Ray exiting cleanly...", flush=True)
        if keyboard_listener and keyboard_listener.is_alive():
            keyboard_listener.stop()
        self.root.destroy()

    def check_queue(self):
        """
        Polls the queue every 50ms for events sent from background threads.
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
                elif action == "startup_notice":
                    self.show_startup_notice(payload.get("status"), payload.get("message"))
                elif action == "dismiss_bubble":
                    if self.root.state() != "withdrawn":
                        self.hide_window()
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

def is_space_key(key):
    """
    Checks if a key event represents the Space key.
    Handles pynput Key.space, character ' ', and Windows virtual key code (VK_SPACE = 32).
    """
    if key == keyboard.Key.space:
        return True
    if isinstance(key, keyboard.KeyCode):
        if getattr(key, "vk", None) == 32:
            return True
        if key.char == " ":
            return True
    return False


def is_shortcut_key(key):
    """Check if the given key is part of our shortcut combination (Ctrl + Alt + Space)."""
    if key in CTRL_KEYS or key in ALT_KEYS:
        return True
    if is_space_key(key):
        return True
    return False


def is_j_key(key):
    """Deprecated alias preserved for backward compatibility."""
    return is_space_key(key)


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

        # Temporarily release Alt and Shift so the active application registers clean 'Ctrl + C'
        keyboard_controller.release(keyboard.Key.alt)
        keyboard_controller.release(keyboard.Key.alt_l)
        keyboard_controller.release(keyboard.Key.alt_r)
        if hasattr(keyboard.Key, "alt_gr"):
            keyboard_controller.release(keyboard.Key.alt_gr)
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
    Runs in a background thread when Ctrl + Alt + Space is triggered.
    Steps:
    1. Captures selected text without blocking the UI.
    2. If no text is selected, tells the UI to notify the user.
    3. If text is selected, immediately opens UI with 'Thinking...' status.
    4. Makes non-blocking local HTTP request to Ollama (llama3.2:1b).
    5. Posts final explanation (or error message) to the UI queue.
    """
    if run_id is not None:
        emit_profile_event("activation_started", run_id)

    print("\n--- Shortcut detected: Ctrl + Alt + Space ---", flush=True)

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
    alt_held = any(k in pressed_keys for k in ALT_KEYS)
    space_pressed_now = is_space_key(key)

    if ctrl_held and alt_held and space_pressed_now:
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

    # Esc only dismisses the visible floating panel; it does not terminate the background process
    if key == keyboard.Key.esc:
        ui_queue.put(("dismiss_bubble", None))


def main():
    global keyboard_listener

    setup_safe_logging()

    print("=" * 60, flush=True)
    print("Kya-Ray - Context-Aware Desktop Companion", flush=True)
    print("=" * 60, flush=True)
    print("Instructions:", flush=True)
    print("  * Select text in any window and press Ctrl + Alt + Space.", flush=True)
    print("  * A compact floating panel displays a concise AI response.", flush=True)
    print("  * Drag anywhere on the panel to reposition it.", flush=True)
    print("  * Press Esc or click [X] to dismiss the panel.", flush=True)
    print("  * Click 'Exit' or right-click to exit completely.", flush=True)
    print("=" * 60 + "\n", flush=True)

    root = tk.Tk()
    app = FloatingBubbleWindow(root)

    # Non-blocking startup prerequisite check
    def _run_prereq_check():
        status, msg = check_ollama_prerequisites()
        if status != "ready":
            ui_queue.put(("startup_notice", {"status": status, "message": msg}))

    threading.Thread(target=_run_prereq_check, daemon=True).start()

    try:
        keyboard_listener = keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
        )
        keyboard_listener.start()
    except Exception as error:
        print(f"\n[Error] Failed to start keyboard listener: {error}", flush=True)
        print("Please ensure your system has appropriate permissions to monitor keyboard input.", flush=True)
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