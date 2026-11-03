"""
Desktop utility modules: configuration, logging, and clipboard handling.
"""

from desktop.utils.config import (
    APP_NAME,
    APP_VERSION,
    OLLAMA_API_URL,
    OLLAMA_MODEL,
    REQUEST_TIMEOUT_SECONDS,
    DEFAULT_WINDOW_WIDTH,
    DEFAULT_WINDOW_HEIGHT,
    MIN_WINDOW_HEIGHT,
    MAX_WINDOW_HEIGHT,
    LIGHT_THEME,
    INTENT_DISPLAY_LABELS,
    get_system_theme,
    get_mouse_position,
)
from desktop.utils.logger import (
    get_log_dir,
    get_log_file_path,
    setup_safe_logging,
    SafeOutput,
)
from desktop.utils.clipboard import (
    get_clipboard_text,
    set_clipboard_text,
    preserve_clipboard,
    capture_selected_text,
)

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "OLLAMA_API_URL",
    "OLLAMA_MODEL",
    "REQUEST_TIMEOUT_SECONDS",
    "DEFAULT_WINDOW_WIDTH",
    "DEFAULT_WINDOW_HEIGHT",
    "MIN_WINDOW_HEIGHT",
    "MAX_WINDOW_HEIGHT",
    "LIGHT_THEME",
    "INTENT_DISPLAY_LABELS",
    "get_system_theme",
    "get_mouse_position",
    "get_log_dir",
    "get_log_file_path",
    "setup_safe_logging",
    "SafeOutput",
    "get_clipboard_text",
    "set_clipboard_text",
    "preserve_clipboard",
    "capture_selected_text",
]

