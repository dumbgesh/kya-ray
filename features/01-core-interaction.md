# Feature 01: Core Interaction (Global Hotkey & Activation Lifecycle)

## Status
`In Progress`

---

## Purpose
The Core Interaction system provides an instant, universal gateway for invoking Kya-Ray from any running application without switching focus away from the user's active work. It monitors low-level keyboard inputs globally, orchestrates non-blocking activation tasks, and manages clean application teardown.

---

## User Experience
1. A user is working inside any desktop application (web browser, code editor, PDF viewer, document editor).
2. The user highlights content on their screen.
3. The user presses **`Ctrl + Shift + J`**.
4. The active application is not interrupted, and Kya-Ray immediately acknowledges the input by showing a lightweight floating bubble with a "Thinking..." status indicator.
5. If the user presses **`Esc`** at any point, Kya-Ray terminates cleanly and releases all OS hooks.
6. If the user clicks the **`✕`** (close) icon on the bubble header, the bubble disappears, remaining ready for the next hotkey invocation.

---

## Intended Behaviour
- **Global Accessibility**: The shortcut must trigger regardless of which window, screen, or application currently holds OS focus.
- **Repeat Suppression (Debounce)**: Holding down `Ctrl + Shift + J` must trigger exactly one activation event, not an uncontrolled flood of repeated inferences.
- **Modifier Agnosticism**: Both left and right variants of modifier keys (`Ctrl_L`, `Ctrl_R`, `Shift_L`, `Shift_R`) must be accepted seamlessly.
- **Non-Blocking Operation**: The hotkey handler must immediately delegate downstream tasks (clipboard capture, inference, UI rendering) to background daemon threads so the keyboard hook remains responsive.
- **Graceful Failure Handling**: If global keyboard listening fails (e.g., due to insufficient OS privileges or an input hooking conflict), Kya-Ray must exit with a clear, user-actionable terminal error instead of hanging or crashing silently.
- **Clean Exit**: Pressing `Esc` must cleanly stop the low-level keyboard listener, destroy UI resources, and exit the Python runtime without leaving orphan processes or active input hooks.

---

## Current Implementation

### Verified Code Location
Implemented in [`prototype/main.py`](../prototype/main.py#L23-L65).

### Mechanism
- **Keyboard Listener**: Uses `pynput.keyboard.Listener` in non-blocking mode.
- **Key Tracking**: Maintains an in-memory set `pressed_keys` updated via `on_press` and `on_release` callbacks.
- **Modifier Sets**:
  ```python
  CTRL_KEYS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
  SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
  ```
- **Windows Virtual Key Handling**: On Windows, when `Ctrl` is held, standard key mapping often translates `'J'` into ASCII line feed (`\n`, ASCII 10). The prototype explicitly matches both the virtual key code (`vk=74` for `ord('J')`) and character representations via `is_j_key()`.
- **Trigger Latch**: Uses a boolean latch `shortcut_triggered` to prevent re-triggering while keys remain held down. The latch resets inside `on_release()` when any shortcut key is released.
- **Thread Spawning**: When activated, it increments an atomic `_run_counter` and spawns a daemon thread executing `process_shortcut_event(run_id)`.
- **Exit Hook**: When `key == keyboard.Key.esc`, `on_release()` puts a `("quit", None)` tuple onto `ui_queue`, stops the listener, and signals the Tkinter main loop to exit.

---

## Current Implementation vs. Desired Behaviour

| Dimension | Current Prototype | Desired Production Behaviour |
| :--- | :--- | :--- |
| **Shortcut Configuration** | Hardcoded to `Ctrl + Shift + J`. | User-configurable hotkey via configuration file or settings dialog. |
| **Runtime Persistence** | Foreground console process; closes when terminal closes. | Background tray application with autostart and silent background execution. |
| **Elevation & Focus** | Fails to detect hotkeys or capture text if the active window is running with Administrator privileges (Windows UIPI). | Graceful privilege elevation or clear notification when operating over elevated windows. |
| **Multi-Monitor Cursor Anchoring** | Assumes primary display geometry for screen clamping. | Multi-monitor DPI-aware display positioning. |
| **Conflict Resolution** | Silently conflicts if another application registers the exact same hook. | Reports shortcut collision and offers alternatives. |

---

## Acceptance Criteria
- [x] Pressing `Ctrl + Shift + J` detects hotkey accurately on Windows using virtual key code `vk=74`.
- [x] Supports both left and right `Ctrl` and `Shift` keys.
- [x] Holding the keys triggers only one single activation run.
- [x] Pressing `Esc` exits the application cleanly and terminates listener threads.
- [ ] Hotkey can be customized without editing source code (`Planned`).
- [ ] Runs persistently in the Windows system tray without requiring an open terminal (`Planned`).
- [ ] Recovers cleanly if the display server or desktop session is locked/unlocked (`Planned`).

---

## Edge Cases
1. **Windows UIPI (User Interface Privilege Isolation)**: When an active foreground window runs as Administrator (elevated), standard-integrity input hooks may be blocked by Windows security from receiving keystrokes or injecting synthetic `Ctrl + C`.
2. **Terminal Control Characters**: Holding `Ctrl` modifies standard ASCII codes. Handled in prototype via explicit `vk=74` checking.
3. **Rapid Key Tapping**: Fast repeated triggering could queue overlapping tasks. The prototype assigns monotonic `run_id` values to each run; however, overlapping clipboard captures may still conflict.
4. **Non-Interactive Environments**: Headless environments or remote desktop sessions without desktop interaction will fail to hook the keyboard listener.

---

## Dependencies
- **Libraries**: `pynput` (cross-platform keyboard hooking), `tkinter` (UI event loop), `ctypes` (Win32 API bindings).
- **Subsystems**:
  - [02-context-capture.md](02-context-capture.md) (invoked immediately upon hotkey trigger).
  - [05-floating-bubble-ui.md](05-floating-bubble-ui.md) (UI thread notified via `ui_queue`).
  - [06-performance-and-reliability.md](06-performance-and-reliability.md) (latency profiling milestones).

---

## Open Questions
- **Open question**: Should `Ctrl + Shift + J` remain the permanent default, or should Kya-Ray adopt a configurable single-modifier global shortcut (e.g., `Alt + Space`, `Win + K`)?
- **Open question**: Should pressing `Esc` close the entire application, or should `Esc` merely dismiss the active bubble when visible, requiring a tray menu action to exit completely?
