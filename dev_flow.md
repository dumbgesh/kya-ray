
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

