"""
backend/config.py - Centralized configuration and environment settings for backend.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional


def get_env_file_candidates() -> List[Path]:
    """Returns candidate paths for .env in search priority order."""
    candidates = []
    # 1. Next to the frozen executable (critical for standalone packaged application)
    if getattr(sys, "frozen", False):
        try:
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / ".env")
        except Exception:
            pass

    # 2. Current working directory
    try:
        cwd_path = Path.cwd() / ".env"
        if cwd_path not in candidates:
            candidates.append(cwd_path)
    except Exception:
        pass

    # 3. Source repository root relative to backend package
    try:
        repo_root = Path(__file__).resolve().parent.parent / ".env"
        if repo_root not in candidates:
            candidates.append(repo_root)
    except Exception:
        pass

    return candidates


def load_env_file(override: bool = False) -> None:
    """Loads environment variables from .env if present without stomping on explicitly set variables."""
    for env_path in get_env_file_candidates():
        if not env_path.is_file():
            continue

        try:
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=env_path, override=override)
            return
        except ImportError:
            # Robust fallback parser if python-dotenv is not installed
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, _, val = line.partition("=")
                            key = key.strip()
                            val = val.strip().strip("'\"")
                            if key:
                                if override or key not in os.environ:
                                    os.environ[key] = val
                return
            except Exception:
                pass


# Automatically load environment variables upon config import
load_env_file(override=False)


def safe_int(
    val: Any,
    default: int,
    min_val: Optional[int] = None,
    max_val: Optional[int] = None,
) -> int:
    """Safely parses an integer configuration value with fallback and boundary clamping."""
    if val is None or not str(val).strip():
        return default
    try:
        parsed = int(str(val).strip())
        if min_val is not None and parsed < min_val:
            return default
        if max_val is not None and parsed > max_val:
            return default
        return parsed
    except (ValueError, TypeError):
        return default


def safe_float(
    val: Any,
    default: float,
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
) -> float:
    """Safely parses a float configuration value with fallback and boundary clamping."""
    if val is None or not str(val).strip():
        return default
    try:
        parsed = float(str(val).strip())
        if min_val is not None and parsed < min_val:
            return default
        if max_val is not None and parsed > max_val:
            return default
        return parsed
    except (ValueError, TypeError):
        return default


class Settings:
    """Application settings read from environment variables."""

    def __init__(self):
        # Ensure latest env vars are loaded without clobbering active overrides
        load_env_file(override=False)

        # Service Information
        self.APP_NAME: str = "Kya-Ray Cloud Backend"
        self.APP_VERSION: str = "1.0.0"

        # Server Settings
        self.HOST: str = os.getenv("BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
        self.PORT: int = safe_int(os.getenv("BACKEND_PORT"), 8000, min_val=1, max_val=65535)
        self.ENVIRONMENT: str = os.getenv("BACKEND_ENVIRONMENT", "development").strip() or "development"
        self.REQUEST_TIMEOUT_SECONDS: float = safe_float(
            os.getenv("BACKEND_TIMEOUT_SECONDS"), 30.0, min_val=1.0, max_val=300.0
        )

        # GroqCloud Settings: Windows Credential Manager takes priority, with env fallback
        stored_key = None
        try:
            from desktop.utils.credentials import get_stored_api_key
            stored_key = get_stored_api_key()
        except Exception:
            pass
        self.GROQ_API_KEY: str = (stored_key or os.getenv("GROQ_API_KEY", "")).strip()
        self.GROQ_MODEL: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip() or "qwen/qwen3.8-27b"

        # Limits & Constraints
        self.MAX_INPUT_LENGTH: int = 20000
        self.ALLOWED_CORS_ORIGINS: tuple = (
            "http://localhost",
            "http://127.0.0.1",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        )


def get_settings() -> Settings:
    """Returns singleton-style application settings."""
    return Settings()
