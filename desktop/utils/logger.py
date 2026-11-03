"""
Safe Logging and Output Redirection for Kya-Ray Desktop.
Handles windowed (non-console) output redirection to local AppData log file.
"""

import os
import sys


def get_log_dir():
    """Returns the dedicated directory for Kya-Ray application logs."""
    appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    log_dir = os.path.join(appdata, "Kya-Ray")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        pass
    return log_dir


def get_log_file_path():
    """Returns the absolute path to the local diagnostic log file."""
    return os.path.join(get_log_dir(), "kya-ray.log")


class SafeOutput:
    """
    Stream wrapper that directs output to both the original console stream (if available)
    and the local AppData log file without crashing windowed/GUI executables.
    """

    def __init__(self, original_stream, log_path):
        self.original = original_stream
        self.log_path = log_path

    def write(self, text):
        if self.original:
            try:
                self.original.write(text)
            except UnicodeEncodeError:
                try:
                    encoding = getattr(self.original, "encoding", "ascii") or "ascii"
                    safe_text = text.encode(encoding, errors="replace").decode(encoding)
                    self.original.write(safe_text)
                except Exception:
                    pass
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

    def isatty(self) -> bool:
        if self.original and hasattr(self.original, "isatty"):
            try:
                return bool(self.original.isatty())
            except Exception:
                return False
        return False

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


def setup_safe_logging():
    """
    Redirects stdout and stderr to a safe wrapper writing to %LOCALAPPDATA%\\Kya-Ray\\kya-ray.log.
    Ensures GUI/PyInstaller windowed applications do not fail on print() calls.
    """
    log_file = get_log_file_path()

    if sys.stdout is None or not hasattr(sys.stdout, "write"):
        sys.stdout = SafeOutput(None, log_file)
    else:
        sys.stdout = SafeOutput(sys.stdout, log_file)

    if sys.stderr is None or not hasattr(sys.stderr, "write"):
        sys.stderr = SafeOutput(None, log_file)
    else:
        sys.stderr = SafeOutput(sys.stderr, log_file)

    return log_file

