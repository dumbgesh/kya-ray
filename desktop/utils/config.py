"""
Centralized Configuration and Constants for Kya-Ray Desktop.
"""

import ctypes
import os

# Application Metadata
APP_NAME = "Kya-Ray"
APP_VERSION = "1.0.0"
APP_TARGET_VERSION = "1.0.0"

# Local AI Engine (Ollama) Settings
OLLAMA_HOST = "http://127.0.0.1:11434"
OLLAMA_API_URL = f"{OLLAMA_HOST}/api/generate"
OLLAMA_TAGS_URL = f"{OLLAMA_HOST}/api/tags"
OLLAMA_VERSION_URL = f"{OLLAMA_HOST}/api/version"
OLLAMA_MODEL = "llama3.2:1b"
REQUEST_TIMEOUT_SECONDS = 30
MODEL_OPTIONS = {
    "temperature": 0.3,
    "top_p": 0.9,
    "num_predict": 120,
    "think": False,
}

# Cloud Backend (FastAPI + GroqCloud) Settings
BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
try:
    _raw_port = int(os.getenv("BACKEND_PORT", "8000"))
    BACKEND_PORT = _raw_port if 1 <= _raw_port <= 65535 else 8000
except (ValueError, TypeError):
    BACKEND_PORT = 8000

DEFAULT_BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
BACKEND_BASE_URL = os.getenv("KYA_RAY_BACKEND_URL", DEFAULT_BACKEND_URL).strip() or DEFAULT_BACKEND_URL
BACKEND_GENERATE_URL = f"{BACKEND_BASE_URL}/api/v1/ai/generate"
BACKEND_STREAM_URL = f"{BACKEND_BASE_URL}/api/v1/ai/stream"
BACKEND_HEALTH_URL = f"{BACKEND_BASE_URL}/health"

# Hotkey settings
SHORTCUT_COMBINATION_NAME = "Ctrl + Alt + Space"

# UI Geometry & Layout Limits
DEFAULT_WINDOW_WIDTH = 620
DEFAULT_WINDOW_HEIGHT = 340
MIN_WINDOW_WIDTH = 380
MIN_WINDOW_HEIGHT = 200
MAX_WINDOW_WIDTH = 900
MAX_WINDOW_HEIGHT = 650
PANEL_CORNER_RADIUS = 12

# Minimal Light Theme Color Palette
LIGHT_THEME = {
    "mode": "light",
    "bubble_fill": "#ffffff",      # Crisp white background
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

# User-facing Intent Display Labels
INTENT_DISPLAY_LABELS = {
    "-explain": "Explain",
    "-summarize": "Summary",
    "-code": "Code",
    "-create": "Create",
}


def get_system_theme():
    """
    Returns the consistent minimal light theme palette for Kya-Ray:
    - Crisp white background (#ffffff)
    - Dark, high-contrast body text (#0f172a)
    - Restrained blue accent (#0284c7)
    - Subtle border (#e2e8f0)
    Enforces product identity reliably regardless of whether Windows OS is in dark mode.
    """
    return dict(LIGHT_THEME)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


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

