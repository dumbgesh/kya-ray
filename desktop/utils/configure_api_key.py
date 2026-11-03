"""
desktop/utils/configure_api_key.py - Interactive CLI/Helper for configuring GROQ_API_KEY.
Ensures beta testers can easily configure their Groq credentials without manually editing files.
"""

import os
import sys
from pathlib import Path


def get_target_env_path() -> Path:
    """Identifies the destination .env file path."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / ".env"
    # In source repository, default to repo root or cwd
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / ".env"


def configure_api_key(api_key: str = "", model: str = "qwen/qwen3.8-27b") -> bool:
    """Writes or updates GROQ_API_KEY in the target .env file."""
    api_key = api_key.strip()
    if not api_key:
        print("[Error] API Key cannot be empty.", flush=True)
        return False

    if not api_key.startswith("gsk_"):
        print("[Warning] Groq API keys typically begin with 'gsk_'. Please ensure your key is valid.", flush=True)

    env_path = get_target_env_path()

    existing_lines = []
    if env_path.is_file():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                existing_lines = f.readlines()
        except Exception:
            pass

    key_written = False
    model_written = False
    new_lines = []

    for line in existing_lines:
        trimmed = line.strip()
        if trimmed.startswith("GROQ_API_KEY="):
            new_lines.append(f"GROQ_API_KEY={api_key}\n")
            key_written = True
        elif trimmed.startswith("GROQ_MODEL="):
            new_lines.append(f"GROQ_MODEL={model}\n")
            model_written = True
        else:
            new_lines.append(line)

    if not key_written:
        new_lines.append(f"GROQ_API_KEY={api_key}\n")
    if not model_written:
        new_lines.append(f"GROQ_MODEL={model}\n")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"\n[Success] Configuration saved to: {env_path}", flush=True)
        return True
    except Exception as e:
        print(f"[Error] Failed to write .env file: {e}", flush=True)
        return False


def interactive_prompt():
    """Interactive command-line wizard for first-time setup."""
    print("=" * 60)
    print(" Kya-Ray - GroqCloud API Key Setup Wizard")
    print("=" * 60)
    print()
    print("Kya-Ray requires a free Groq API key for high-speed cloud intelligence.")
    print("You can create a free key in 30 seconds at: https://console.groq.com/keys")
    print()

    env_path = get_target_env_path()
    if env_path.is_file():
        print(f"Active configuration file detected at: {env_path}")
        print()

    while True:
        try:
            key_input = input("Enter or paste your Groq API Key (starts with gsk_): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            sys.exit(0)

        if not key_input:
            print("API Key cannot be blank. Try again (or press Ctrl+C to cancel).")
            continue

        if configure_api_key(key_input):
            print()
            print("Setup Complete! You can now launch Kya-Ray:")
            print("  - Highlight text anywhere on screen.")
            print("  - Press Ctrl + Alt + Space.")
            print("=" * 60)
            break


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].strip():
        # Command line parameter provided
        success = configure_api_key(sys.argv[1])
        sys.exit(0 if success else 1)
    else:
        interactive_prompt()

