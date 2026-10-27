# Feature 02: Context Capture (Selected Text & Clipboard Bridge)

## Status
`In Progress`

---

## Purpose
The Context Capture system extracts the user's highlighted screen content from external desktop applications without requiring manual copy-pasting. It forms the primary input pipeline feeding downstream intent identification and AI generation.

---

## User Experience
1. The user highlights a passage, error message, or code block in any software application.
2. The user triggers the hotkey (`Ctrl + Shift + J`).
3. Kya-Ray programmatically captures the selection in the background.
4. **When text is selected**: The floating bubble opens immediately in "Thinking..." mode displaying a truncated preview of the captured text.
5. **When nothing is selected**: The floating bubble appears displaying a clear notice:
   > *"No text was selected. Please highlight some text in any window and press Ctrl + Shift + J again."*
6. The user's pre-existing clipboard contents are preserved and restored.

---

## Intended Behaviour
- **Seamless Acquisition**: Capture highlighted text reliably across web browsers, text editors, PDF viewers, terminals, and office suites.
- **Clipboard Non-Destructiveness**: Any content existing on the user's OS clipboard prior to activation must be restored immediately following the capture operation.
- **Empty Selection Handling**: When activation occurs without an active selection, the pipeline must abort cleanly without dispatching wasteful requests to the AI engine.
- **Strict Privacy**: Selected text is strictly confidential user data. It must never be written to telemetry sockets, external network requests, or persistent diagnostic logs.
- **Low Latency**: The capture sequence must execute within 100ms to maintain instantaneous perceived responsiveness.

---

## Current Implementation

### Verified Code Location
Implemented in [`prototype/main.py`](../prototype/main.py#L550-L630) within `capture_selected_text()` and `process_shortcut_event()`.

### Mechanism: Simulated Clipboard Bridge
1. **Preserve Clipboard**: Reads existing clipboard content using `pyperclip.paste()` and saves it to a local variable `previous_clipboard`.
2. **Clear Clipboard**: Writes an empty string (`pyperclip.copy("")`) and sleeps for 20ms to allow the OS clipboard to flush.
3. **Release Modifiers**: Explicitly issues `keyboard_controller.release()` for `Shift`, `Shift_L`, and `Shift_R` so the active target application interprets the subsequent keystroke as standard `Ctrl + C` rather than `Ctrl + Shift + C`.
4. **Simulate Copy**: Presses and releases `Ctrl + C` using `keyboard.Controller`.
5. **Read New Text**: Sleeps for 80ms to permit target application copy handlers to process, then reads `pyperclip.paste()`.
6. **Restore Clipboard**: In a `finally` block, restores `previous_clipboard` via `pyperclip.copy(previous_clipboard)`.

### Empty Selection Pipeline Abort
Inside `process_shortcut_event()`:
```python
if not captured_text or not captured_text.strip():
    if run_id is not None:
        emit_profile_event("pipeline_aborted", run_id, error="no_selection")
    ui_queue.put(("no_selection", {"run_id": run_id}))
    return
```
When no text is captured, the request is aborted prior to initiating any AI inference or network call.

---

## Verified Limitations of Current Implementation

| Limitation | Root Cause | Consequence |
| :--- | :--- | :--- |
| **Fixed Sleep Delays** | Hardcoded sleep intervals (20ms + 80ms = 100ms total). | Imposes a minimum 100ms floor on capture latency; on slow or heavily loaded systems, 80ms may be insufficient, causing missed selections. |
| **Clipboard History Polluters** | Windows Clipboard History (`Win + V`) or clipboard managers (Ditto, 1Password) intercept clipboard changes. | The temporary copy operation may appear in the user's permanent clipboard history, leaking selections into clipboard history logs. |
| **Rich & Non-Text Media** | `pyperclip` only reads plain text strings. | Formatted rich text, tabular structures, images, screenshots, and terminal ANSI sequences are stripped or missed. |
| **Elevated Windows (UIPI)** | Windows User Interface Privilege Isolation blocks standard user processes from sending synthetic input to Admin windows. | Capturing text from Task Manager, Registry Editor, or elevated command prompts fails silently. |
| **Clipboard Race Conditions** | If another process or the user copies content during the 100ms window, clipboard contents can become scrambled. | High-frequency activations may overwrite clipboard data. |

---

## Privacy Expectations & Telemetry Boundaries
- **Telemetry Isolation**: The profiler hook `emit_profile_event()` in `main.py` explicitly omits captured text. Telemetry packets only contain `run_id`, milestone names, monotonic timestamps, error categories, and numeric Ollama token/duration metadata.
- **Local Memory Boundary**: Captured text is stored only in local Python variables on the worker thread stack and passed to the local loopback Ollama endpoint (`127.0.0.1:11434`). It is never transmitted across the network.
- **Verified Code Check**: Sanitization logic in `sanitize_ollama_metrics()` strips all strings, preserving only numeric timing metrics.

---

## Future Improvements (Clearly Separated from Existing Code)

### Planned & Evaluated Alternatives
1. **Windows UI Automation (UIA) Provider**:
   - Query the focused element's `TextPattern` or `ValuePattern` directly via accessibility APIs without tampering with the OS clipboard.
   - *Status*: `Needs Decision` (high architectural complexity, varies across electron and legacy Win32 apps).
2. **Context-Aware Window Identification**:
   - Capture foreground window metadata (process name, window title, URL) to inform intent inference (e.g., code editor vs. browser document).
   - *Status*: `Planned`.
3. **Screen OCR Fallback**:
   - For protected PDFs, remote desktop windows, or video frames where text cannot be selected, offer a quick-snip region OCR.
   - *Status*: `Planned`.

---

## Acceptance Criteria
- [x] Captures selected plain text across standard Windows applications via simulated `Ctrl + C`.
- [x] Accurately detects empty selection and renders the `no_selection` notification bubble.
- [x] Restores the user's original clipboard content after capture.
- [x] Emits diagnostic telemetry indicating capture start/completion without leaking text content.
- [ ] Eliminate clipboard pollution in Windows Clipboard History (`Win + V`) (`Needs Decision`).
- [ ] Provide non-destructive capture via UI Automation where supported (`Planned`).

---

## Edge Cases
- **Terminals & Consoles**: Some Windows terminals use `Ctrl + Shift + C` or Enter to copy; standard `Ctrl + C` can send a `SIGINT` cancel signal instead of copying.
- **Read-Only / Protected Software**: Document viewers with copy protection disable the copy command, causing false `no_selection` alerts.
- **Massive Selections**: Selecting hundreds of pages of text can cause large memory allocation and slow down the clipboard bridge.

---

## Dependencies
- **Libraries**: `pyperclip`, `pynput`, `time`.
- **Subsystems**:
  - [01-core-interaction.md](01-core-interaction.md) (triggers capture).
  - [04-ai-response-engine.md](04-ai-response-engine.md) (consumes captured text).
  - [07-privacy-and-security.md](07-privacy-and-security.md) (enforces data isolation).

---

## Open Questions
- **Open question**: Should Kya-Ray adopt the Windows Accessibility UI Automation (UIA) API to eliminate the clipboard bridge entirely, or keep clipboard capture as a universal fallback?
- **Open question**: How should Kya-Ray handle terminal applications where sending synthetic `Ctrl + C` aborts the currently running command?
