# Kya-Ray Beta Testing Guide (v0.2.0-beta)

Thank you for participating in the controlled beta testing program for **Kya-Ray**!

This guide contains everything you need to get set up, test the assistant, and provide structured feedback.

---

## 1. Quick Start (3-Minute Setup)

1. **Extract the ZIP Archive:**
   Extract `Kya-Ray-v0.2.0-beta-win64.zip` to any folder on your computer.

2. **Install or Run Portably:**
   - **Recommended:** Double-click **`Install-Kya-Ray.bat`** to install Kya-Ray to your Start Menu and Desktop.
   - **Or Portable:** Simply double-click **`START_KYA_RAY.bat`**.

3. **Configure Your Free Groq API Key (Graphical Setup):**
   - On first launch, the native setup window opens: *"Let's get you started."*
   - If you do not have a key, click the link to create one for free at [https://console.groq.com/keys](https://console.groq.com/keys) (takes 30 seconds; no credit card).
   - Paste your key (starts with `gsk_...`) and click **Connect and continue**. Kya-Ray verifies the key with Groq and stores it securely in Windows Credential Manager.

4. **Try It Out:**
   - Highlight any text in your browser, code editor, or document.
   - Press **`Ctrl + Alt + Space`**.
   - Watch the floating assistant stream an answer near your cursor!

---

## 2. Beta Testing Checklist

Please test the following everyday scenarios during your trial:

- [ ] **First-Time Setup:** Launch Kya-Ray, enter your Groq key in the setup dialog, and confirm the connection succeeds.
- [ ] **Code Analysis:** Highlight a code snippet in VS Code, Notepad, or a browser and press `Ctrl + Alt + Space`.
- [ ] **Error Explanation:** Highlight a terminal error message or stack trace.
- [ ] **Article Summarization:** Highlight a paragraph or meeting notes in a document.
- [ ] **Quick Dismissal:** Press `Esc` or `Ctrl + W` while a response is streaming to test cancellation.
- [ ] **Copy Functionality:** Click the Copy button or press `Ctrl + C` and verify the full answer pastes cleanly into another window.
- [ ] **Clipboard Preservation:** Copy an important text or link, use Kya-Ray, and verify your original clipboard item is still there when you paste (`Ctrl + V`).
- [ ] **Window Dragging & Resizing:** Drag the header to reposition; drag the bottom-right grip to resize.
- [ ] **Multi-Monitor (if applicable):** Trigger Kya-Ray on a secondary monitor and verify window placement.
- [ ] **Uninstallation:** (Optional) Verify `uninstall.bat` removes the application cleanly.

---

## 3. Bug Reporting Instructions

If you run into any crash, unexpected behavior, or strange UI layout:

1. **Check the Diagnostic Log:**
   Open Windows Explorer and navigate to:
   `%LOCALAPPDATA%\Kya-Ray\kya-ray.log`
   *(This log contains process startup and error messages; it does NOT record your personal text).*

2. **Capture Relevant Details:**
   - What application were you using when it happened? (e.g. Chrome, VS Code, Word, Adobe Acrobat)
   - What text was highlighted? (or describe its general structure)
   - What was the observed behavior vs. expected behavior?
   - A screenshot of the Kya-Ray window if visible.

3. **Submit Your Report:**
   Copy the feedback template below and send it to the development team.

---

## 4. Beta Tester Feedback Template

```text
=== KYA-RAY BETA FEEDBACK ===

Tester Name: 
Windows Version: (e.g. Windows 11 23H2 / Windows 10 22H2)
Screen Setup: (e.g. Single 1080p, Dual Monitor 1440p)

1. Overall Impression:
   [ ] Excellent  [ ] Good  [ ] Needs Work  [ ] Broken

2. Performance & Responsiveness:
   Did AI answers appear quickly? (Yes / No / Slow)
   Comments:

3. Window Behavior & Positioning:
   Did the window position comfortably near your text?
   Did the window size fit short and long responses well?

4. Text Selection & Hotkey Reliability:
   Did Ctrl + Alt + Space work consistently in all your apps?
   Did any application fail to respond to text selection?

5. Issues or Bugs Encountered:
   (Please paste error text or log lines from %LOCALAPPDATA%\Kya-Ray\kya-ray.log)

6. Suggestions for Improvement:
   (What would make Kya-Ray an essential tool in your daily workflow?)
```

---

## 5. Basic Troubleshooting Guide

| Symptom | Cause | Remedy |
| :--- | :--- | :--- |
| **"Backend is reachable, but GROQ_API_KEY is not configured"** | Groq key not configured or revoked. | Right-click the assistant and choose "Configure API Key...". |
| **"Could not connect to Kya-Ray Cloud Backend"** | The local backend was blocked or crashed. | Run `START_KYA_RAY.bat` or reboot Kya-Ray. |
| **Nothing happens when pressing Ctrl + Alt + Space** | Target app running as Admin or no text selected. | Make sure text is highlighted. If target app is Admin, run Kya-Ray as Administrator. |
| **"GroqCloud rate limit exceeded"** | Free-tier rate limit hit temporarily. | Wait 15 seconds and try again. |
| **Hotkeys stop responding** | Another app registered `Ctrl + Alt + Space`. | Right-click the assistant to Exit and restart Kya-Ray. |

