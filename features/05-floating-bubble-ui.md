# Feature 05: Floating Bubble UI (Always-on-Top Speech Bubble)

## Status
`In Progress`

---

## Purpose
The Floating Bubble UI is Kya-Ray's visual surface. It delivers contextual explanations, summaries, and suggestions right beside the user's active cursor without stealing operating system focus, minimizing workflow disruption.

---

## User Experience
1. **Trigger**: The user highlights content and triggers the hotkey (`Ctrl + Alt + Space`).
2. **Contextual Placement**: A sleek, dark speech-bubble card smoothly appears adjacent to the user's mouse cursor, pinned above the active application.
3. **In-Flight Feedback**: While inference runs, the header badge shows `"Thinking with llama3.2:1b..."` and displays a truncated preview of the selection.
4. **Answer Delivery**: Once generation finishes, the status updates to `"Ready"` (green accent), and the explanation appears formatted cleanly in the content pane.
5. **Direct Manipulation**:
   - The user can click and drag the header to relocate the bubble anywhere on screen.
   - The user can click the top-right **`✕`** icon or bottom **`Close`** button to dismiss the bubble.
   - The underlying application retains keyboard and mouse focus throughout.

---

## Intended Behaviour
- **Non-Intrusive Floating Presence**: The bubble must float permanently on top of all windows (including IDEs and fullscreen browsers) without stealing OS focus or breaking user typing.
- **Context-Aware Positioning**: Anchor the window 15px offset from the active mouse pointer coordinates (`pt.x + 15`, `pt.y + 15`), automatically clamping against display boundaries so content never renders off-screen.
- **Thread-Safe Rendering**: All GUI modifications must execute strictly on the main thread via a queue polling mechanism.
- **Draggability**: Allow free dragging anywhere on the screen by grabbing the title bar.
- **Visual Clarity**: Clear visual states for Loading, Success, No Selection, and Failure.

---

## Current Implementation (Verified in Codebase)

### Verified Code Location
Implemented in [`prototype/main.py`](../prototype/main.py#L185-L530) via class `FloatingBubbleWindow` (and backward compatibility alias `ResponseWindow`).

### Visual Styling & Geometry
- **Window Framework**: Standard Python `tkinter.Tk` with Canvas polygon rendering.
- **Silhouette**: Rounded comic speech-bubble silhouette with a visible pointed tail (30px base, extending 25px below body) computed via `compute_bubble_polygon()`.
- **Dimensions**: Fixed geometry of `440 x 310` pixels (bubble body + pointed tail).
- **Frameless & Transparent**: Uses `root.overrideredirect(True)` and isolated Windows `-transparentcolor` keying (`#000001` with fallback) so the rectangular window corners are invisible.
- **Z-Order Pinning**: Enforces `root.attributes("-topmost", True)` to remain visible above heavy development environments like VS Code.
- **Color Palette**:
  - Dark Slate bubble fill (`#1e293b`).
  - Darker contrasting header (`#0f172a`).
  - Sky blue glowing 2px border outline (`#38bdf8`).
  - Typography: Windows native `Segoe UI` fonts with fixed sizes.
- **Content Area**: Scrollable read-only text view (`scrolledtext.ScrolledText`) embedded inside the bubble body bounds with disabled keyboard editing.

### Cursor Anchoring Algorithm
```python
def position_bubble(self):
    screen_w = self.root.winfo_screenwidth()
    screen_h = self.root.winfo_screenheight()
    target_x = (screen_w - self.width) // 2
    target_y = (screen_h - self.height) // 3

    mouse_pos = get_mouse_position() # Win32 GetCursorPos via ctypes
    if mouse_pos:
        mx, my = mouse_pos
        if 0 <= mx < screen_w and 0 <= my < screen_h:
            target_x = mx + 15
            target_y = my + 15

    # Boundary Clamping
    if target_x + self.width > screen_w - 15:
        target_x = screen_w - self.width - 15
    if target_y + self.height > screen_h - 45:
        target_y = screen_h - self.height - 45
    ...
```

### UI States Implemented

| State | Status Badge | Content Displayed |
| :--- | :--- | :--- |
| **Generating** | `"Thinking with llama3.2:1b..."` (Sky Blue) | Truncated selection preview (first 220 characters) and waiting notice. |
| **Success** | `"Ready"` (Emerald Green) | Full generated explanation, separator rule, and original selection. |
| **No Selection** | `"No Selection"` (Amber Yellow) | Notice asking user to highlight text and try again. |
| **Error** | `"Explanation Failed"` (Coral Red) | Error description, actionable remediation advice, and selected text. |

### Thread-Safe Bridge
Background worker threads never touch Tkinter widgets directly. They push tuples to `ui_queue`, and the UI thread polls `check_queue()` every 50ms via `self.root.after(50, self.check_queue)`.

---

## Current Prototype vs. Product Vision

| Dimension | Current Prototype (V6) | Long-Term Product Vision |
| :--- | :--- | :--- |
| **Formatting** | Plain text rendering in a `ScrolledText` widget. | Full Markdown rendering (bold, code blocks, syntax highlighting, bulleted lists). |
| **Window Shell** | Tkinter borderless window. | Modern accelerated desktop shell (e.g., PySide/Qt, WebView, or native Win32/DirectComposition). |
| **Window Sizing** | Fixed 440x290 size regardless of answer length. | Dynamic auto-sizing based on response length with max-height constraints. |
| **Follow-up Interaction** | Read-only dismissable card. | Interactive followup chips, single-click copy buttons, and refinement input bar. |
| **Multi-Bubble Pinning** | Single global bubble instance hidden/shown. | Multiple independent floating "sticky note" bubbles that can be pinned to screen locations. |

---

## Acceptance Criteria
- [x] Renders borderless floating card positioned near mouse pointer with screen clamping.
- [x] Remains pinned topmost above VS Code and other applications.
- [x] Header can be dragged smoothly across screen with mouse pointer.
- [x] Handles Generating, Ready, No Selection, and Error states with visual indicators.
- [x] Dismissable via top-right '✕' or bottom 'Close' button without terminating background listener.
- [ ] Render Markdown formatting and formatted code snippets (`Planned`).
- [ ] Auto-size window height dynamically to avoid unnecessary scrollbars on short definitions (`Planned`).
- [ ] Provide one-click "Copy Answer" button (`Planned`).

---

## Edge Cases
- **Multi-Monitor Setup**: `winfo_screenwidth()` queries primary screen dimensions; positioning on secondary monitors with different scaling/resolutions can cause clamping errors.
- **Bottom-Right Screen Corner**: If user triggers hotkey near taskbar corner, bubble must flip above the cursor to remain visible.
- **Focus Stealing**: Tkinter windows can inadvertently capture focus on `deiconify()`. The prototype uses `overrideredirect(True)` to mitigate this.

---

## Dependencies
- **Libraries**: `tkinter`, `ctypes` (Win32 `GetCursorPos`).
- **Subsystems**:
  - [01-core-interaction.md](01-core-interaction.md) (triggers bubble appearance).
  - [04-ai-response-engine.md](04-ai-response-engine.md) (supplies generated text).
  - [06-performance-and-reliability.md](06-performance-and-reliability.md) (tracks render latency via `answer_displayed`).

---

## Open Questions
- **Open question**: Should Tkinter be retained for lightweight portability, or should Kya-Ray transition to a framework supporting modern CSS-like styling and native Markdown rendering?
- **Open question**: How should multi-monitor coordinates be handled when monitors have mixed DPI scaling factors?
