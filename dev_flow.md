
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
- Status: Completed and verified.

## V5 — AI Explanation Integration
- Integrated Ollama local inference directly into `prototype/main.py`.
- Uses Python's standard library `urllib.request` and `json` (zero extra dependencies).
- Calls local endpoint `http://127.0.0.1:11434/api/generate` with model `llama3.2:1b` (`stream: false`).
- Prompt requests concise, beginner-friendly explanations (2-3 sentences max).
- Fully non-blocking: network I/O executes in background thread; UI updates pass safely through `ui_queue`.
- Handles empty selections, network timeouts (30s), missing models (404), and unavailable Ollama service with friendly UI states.
- Status: Completed and verified.

## V6 — Floating Speech-Bubble UI
- Replaced basic window with a compact floating bubble interface (`FloatingBubbleWindow`).
- Borderless floating card styling (`root.overrideredirect(True)`) with dark slate theme and accent border.
- Pinned permanently above normal application windows (`root.attributes("-topmost", True)`), remaining visible when interacting with VS Code.
- Draggable header bar (`<Button-1>`, `<B1-Motion>`) for repositioning the bubble anywhere on screen.
- Smart screen positioning: anchors near active mouse cursor using Win32 `GetCursorPos` with screen clamping; falls back to upper-center.
- Minimal controls: top-right '✕' dismiss button, bottom 'Close' button, and 'Esc' exit.
- Preserved all V1–V5 keyboard shortcuts, text capture, clipboard restoration, and non-blocking Ollama inference.
- Status: Implemented; automated tests passed; ready for manual testing.





