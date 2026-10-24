
# Kya-Ray Development Log

## V1 — Keyboard Shortcut
- Detects `Ctrl + Shift + J`.
- Prevents repeated triggers while keys are held.
- Press `Esc` to exit.
- Status: Working and manually tested.

## V2 — Selected Text Capture
- Captures highlighted text using `Ctrl + C`.
- Prints captured text in the terminal.
- Handles cases where no text is selected.
- Attempts to restore the previous clipboard text.
- Status: Working and manually tested.

## V3 — Basic Response Window
- Displays captured text in a lightweight Tkinter desktop window.
- Shows a clear notice when no text is selected.
- Uses a thread-safe queue to ensure all UI updates run on the main Tkinter thread.
- Includes a 'Close' button to dismiss the window and standard 'X'/Esc controls to exit.
- Status: Implemented; automated tests passed, ready for manual testing.

## V4 — Prepare Local AI
- Verified Ollama installation (Version 0.40.10) in `%LOCALAPPDATA%\Programs\Ollama`.
- Verified Ollama background service is active (`ollama.exe` and `ollama app.exe` running).
- Verified local HTTP API is responsive (`http://127.0.0.1:11434/` returns HTTP 200 "Ollama is running").
- Successfully downloaded and verified model `llama3.2:1b` (1.3 GB).
- Executed successful test inference via local HTTP API (`/api/generate`).
- Status: Completed and verified; ready for integration into prototype.



