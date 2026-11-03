# Feature 07: Privacy & Security (Local-First Architecture & Boundaries)

## Status
`In Progress`

---

## Purpose
The Privacy and Security system defines the boundary conditions protecting user data. Kya-Ray is built around a local-first architecture where sensitive desktop context, code, personal correspondence, and proprietary documents remain strictly confined to the user's local machine.

---

## Verified Privacy Architecture

### Data Flow Diagram
```
┌─────────────────────────────────────────────────────────────┐
│                      LOCAL HOST MACHINE                     │
│                                                             │
│   Active Window (Browser / IDE / Document)                 │
│         │                                                   │
│         │ Selected Text (simulated Ctrl + C)                │
│         ▼                                                   │
│   Kya-Ray Main Process (in-memory thread stack)             │
│         │                                                   │
│         │ Local HTTP POST (127.0.0.1:11434)                 │
│         ▼                                                   │
│   Local Ollama Service (Local llama3.2:1b weights)          │
│                                                             │
│   ───────────────────────────────────────────────────────   │
│   DIAGNOSTIC TELEMETRY ONLY (Loopback UDP 127.0.0.1:49999): │
│   [run_id, milestone, timestamp, numeric_durations]         │
│   *** ZERO USER TEXT OR PROMPTS TRANSMITTED ***             │
└─────────────────────────────────────────────────────────────┘
                              │
                    ══════════╪══════════
                     NO EXTERNAL INTERNET
                    ══════════╪══════════
```

---

## Data Inventory & Boundaries

| Category | Specific Data | Where Stored / Sent | Privacy Boundary Verification |
| :--- | :--- | :--- | :--- |
| **Captured Context** | Text highlighted in the active application. | In-memory Python string on worker thread stack. Sent via HTTP to `http://127.0.0.1:11434/api/generate`. | **Verified**: Never transmitted over external network or written to disk files. |
| **Pre-existing Clipboard** | User's clipboard prior to shortcut invocation. | Temporarily saved in local Python memory variable for ~100ms, then immediately restored. | **Verified**: Restored in `finally` block of `capture_selected_text()`. |
| **Model Inferences** | Generated explanations or summaries. | Stored in memory; pushed to `ui_queue` and rendered to Tkinter text widget. | **Verified**: Discarded on window exit or next generation. Not persisted to disk. |
| **Profiler Telemetry** | Monotonic timestamps, event names, token counts, and durations. | Sent via loopback UDP to `127.0.0.1:49999`. | **Verified**: `sanitize_ollama_metrics()` strictly filters on numeric keys only. |

---

## Verified Limitations & Known Privacy Risks

### 1. Clipboard History Leakage
- **Risk**: Modern operating systems (Windows 11 Clipboard History, `Win + V`) and third-party clipboard utilities (e.g., Ditto, Alfred, 1Password) continuously monitor the OS clipboard.
- **Current Behavior**: When Kya-Ray copies selected text via simulated `Ctrl + C`, clipboard managers may record the text into their permanent history database, even if Kya-Ray restores the previous clipboard 80ms later.
- **Evidence**: Verified in [`prototype/main.py`](../prototype/main.py#L550-L578).
- **Mitigation Needed**: Adopt Windows UI Automation (UIA) APIs or use clipboard formats flagged as excluded from clipboard history (`ExcludeClipboardContentFromMonitorProcessing`).

### 2. Error Logging to Standard Output
- **Risk**: In the prototype, `print(captured_text)` is called for debugging:
  ```python
  print("Captured text:", flush=True)
  print(captured_text, flush=True)
  ```
- **Consequence**: Anyone with access to the console terminal or redirected standard streams can view highlighted text.
- **Mitigation Needed**: Strip plain-text printing from production builds; restrict logs strictly to anonymized event codes.

### 3. Localhost Socket Binding
- **Risk**: The diagnostic profiler binds to UDP port 49999 on `127.0.0.1`.
- **Current Behavior**: Any local process running under any user account on the same machine could theoretically listen on or send packets to this UDP socket.
- **Mitigation Implemented**: The profiler payload contains **zero text**, numbers only, mitigating data exposure.

---

## Telemetry Sanitization Code Verification

In [`prototype/main.py`](../prototype/main.py#L47-L75):
```python
ALLOWED_METRIC_KEYS = (
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
    "prompt_eval_count",
    "eval_count",
)

def sanitize_ollama_metrics(raw_metrics):
    if not isinstance(raw_metrics, dict):
        return None
    sanitized = {}
    for key in ALLOWED_METRIC_KEYS:
        val = raw_metrics.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
            sanitized[key] = val
        else:
            sanitized[key] = None
    return sanitized
```
Any arbitrary or prompt text fields (e.g. `"prompt"`, `"response"`, `"context"`) are stripped out.

---

## Acceptance Criteria
- [x] All AI model requests route exclusively to local loopback interface (`127.0.0.1`).
- [x] Diagnostic telemetry socket rejects and strips non-numeric payload fields.
- [x] Previous clipboard content is restored immediately after capture.
- [ ] Remove terminal printing of captured text in non-debug mode (`Planned`).
- [ ] Implement clipboard history exclusion flags for Windows `Win + V` (`Planned`).
- [ ] Verify that third-party Ollama binary does not emit unauthorized external telemetry (`Open question`).

---

## Edge Cases
- **Shared Multi-User Systems**: On shared multi-user workstations, loopback interfaces (`127.0.0.1`) are shared across local user sessions unless firewalled by OS policy.
- **Privileged Access**: A compromised elevated process on the host could inspect memory of the Python process.

---

## Dependencies
- **Subsystems**:
  - [02-context-capture.md](02-context-capture.md) (clipboard access).
  - [04-ai-response-engine.md](04-ai-response-engine.md) (local network boundaries).
  - [06-performance-and-reliability.md](06-performance-and-reliability.md) (telemetry filtering).

---

## Open Questions
- **Open question**: Does the installed version of Ollama send automatic crash reports or update checks over the internet, and should Kya-Ray advise users to run Ollama with `OLLAMA_NO_TELEMETRY=1`?
- **Open question**: How can Kya-Ray ensure synthetic `Ctrl + C` operations do not trigger enterprise Data Loss Prevention (DLP) alerts on managed corporate devices?
