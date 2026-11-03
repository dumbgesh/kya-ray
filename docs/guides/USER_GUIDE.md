# Kya-Ray User Guide (v1.0.0-beta1)

*A context-aware desktop AI companion for Windows.*

Kya-Ray lets you understand and interact with whatever text you are looking at—code, prose, documentation, notes, or data—without ever switching windows or breaking your focus.

---

## 1. What Kya-Ray Does

When reading documentation, reviewing code, reading emails, or troubleshooting an error, you typically have to:
1. Copy the text.
2. Switch windows to a browser or chatbot.
3. Paste the text, craft a prompt, wait for an answer.
4. Copy the response and switch back to your original work.

Kya-Ray reduces this entire cycle to a single keystroke:
- **Highlight text** in any application (browser, VS Code, Notepad, PDF viewer, Slack, Terminal).
- **Press `Ctrl + Alt + Space`**.
- A sleek, floating assistant window appears right near your cursor, showing a clear, intent-tailored response in real time.

---

## 2. System Requirements

- **Operating System:** Windows 10 (version 1809 or higher) or Windows 11 (64-bit).
- **RAM:** Minimum 200 MB free memory.
- **Internet:** Active Internet connection for GroqCloud AI inference.
- **API Key:** A free Groq API key from [GroqCloud Console](https://console.groq.com/keys) (takes 30 seconds; no credit card required).

---

## 3. Installation & Setup

### Option A: Standard Windows Installer (Recommended)
1. Download the release archive `Kya-Ray-v1.0.0-beta1-win64.zip`.
2. Extract the archive into a folder of your choice.
3. Double-click **`Install-Kya-Ray.bat`**.
4. The installer automatically:
   - Installs Kya-Ray to `%LOCALAPPDATA%\Programs\Kya-Ray\`.
   - Creates a **Start Menu** shortcut and a **Desktop** shortcut.
   - Registers Kya-Ray in Windows **Settings > Apps (Installed Apps)** for clean uninstallation.

### Option B: Standalone Portable Mode
You can also run Kya-Ray portably without installing:
1. Extract `Kya-Ray-v1.0.0-beta1-win64.zip`.
2. Open the extracted folder and double-click **`START_KYA_RAY.bat`** (or `Kya-Ray\Kya-Ray.exe`).

---

## 4. First-Time Setup (Graphical API Key Wizard)

Kya-Ray features an integrated native first-launch setup experience:

1. **Launch Kya-Ray**: Double-click the desktop shortcut or `Kya-Ray.exe`.
2. **Setup Dialog**: If no API key is configured, a graphical setup window appears:
   - Title: *"Let's get you started."*
   - Description: *"Kya-Ray uses Groq to power its AI responses. Add your API key to get started."*
3. **Enter Your Free Groq Key**:
   - If you don't have one, click the link: [Get a free API key at console.groq.com/keys &rarr;](https://console.groq.com/keys)
   - Paste your key (starts with `gsk_...`) into the password-masked field. Use the **Show/Hide** toggle to verify your input.
4. **Connect & Continue**: Click **Connect and continue**. Kya-Ray verifies your key directly against the Groq API:
   - Valid keys are encrypted using Windows Data Protection (DPAPI) and stored in Windows Credential Manager under `Kya-Ray/GroqApiKey`.
   - No plaintext `.env` files are stored on disk.
   - The setup dialog closes and Kya-Ray begins listening in the background.

---

## 5. Daily Usage & Features

### Core Shortcut: `Ctrl + Alt + Space`
- Select any text in any application (web page, code file, log output, email).
- Press `Ctrl + Alt + Space`.
- The floating assistant appears adjacent to your mouse cursor and streams an intent-tailored explanation.

### Intelligent Intent Classification
Kya-Ray automatically identifies the nature of your selected text and displays a colored intent badge:
- **Code (Green)**: Detects bugs, syntax errors, security flaws, and performance anti-patterns.
- **Explain (Blue)**: Deconstructs technical concepts, difficult prose, or equations.
- **Summary (Purple)**: Synthesizes meeting notes, articles, or multi-point discussions into structured takeaways.
- **Create (Orange)**: Drafts responses, email replies, or completes templates.

### Window Controls
- **Drag & Move**: Click and drag anywhere on the header bar to move the window.
- **Resize**: Drag the bottom-right grip to resize to your preference.
- **Copy Response**: Click the **Copy** button (or press `Ctrl + C` when no subtext is highlighted in the viewer) to copy the entire markdown response.
- **Dismiss**: Press **`Esc`** or **`Ctrl + W`**, or click **[—]** to hide the assistant.
- **Right-Click Context Menu**:
  - **Configure API Key...**: Opens the update window to change your stored Groq credential.
  - **Exit Kya-Ray**: Completely shuts down the application and background services.

---

## 6. Clipboard Safety & Privacy

- **Clipboard Preservation**: When you trigger `Ctrl + Alt + Space`, Kya-Ray temporarily captures the highlighted text and immediately restores your original clipboard contents. Your copied links or snippets remain safe.
- **Zero Telemetry**: Selected text is sent directly from your computer to GroqCloud via encrypted HTTPS. Kya-Ray operates no intermediary collection servers.
- **Credential Protection**: Keys are never printed in log files or console windows.
