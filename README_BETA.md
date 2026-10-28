# Kya-Ray (v0.1.0-beta for Windows)

*A little context-aware AI desktop companion.*

---

## ⚠️ Important Prerequisites (Please Read First)

Kya-Ray uses **local AI** for all responses. To keep the download lightweight (~30 MB) and protect your device storage, **the multi-gigabyte AI model is not bundled with this application**.

Before running Kya-Ray, please ensure you have:

1. **Ollama for Windows** installed from [ollama.com](https://ollama.com/download/windows).
2. The recommended model downloaded. Open Windows PowerShell or Command Prompt and run:
   ```shell
   ollama pull llama3.2:1b
   ```
   *(Download size: ~1.3 GB. Runs fully locally on your machine.)*
3. The Ollama service running in the background.

---

## 🚀 Quickstart

1. Extract this zip file anywhere on your computer.
2. Ensure Ollama is running with `llama3.2:1b`.
3. Double-click **`START_KYA_RAY.bat`** (or `Kya-Ray\Kya-Ray.exe`).
4. Select any text in any application (browser, PDF, IDE, Word, Notepad).
5. Press **`Ctrl + Alt + Space`**.
6. A compact floating panel will appear near your selection with the AI-generated answer.

---

## ⌨️ Controls & Shortcuts

| Action | Control |
| :--- | :--- |
| **Trigger Kya-Ray** | `Ctrl + Alt + Space` (with text selected) |
| **Dismiss Panel** | Press `Esc` or click `✕` in top-right |
| **Reposition Panel** | Click and drag anywhere on the panel |
| **Context Menu** | Right-click anywhere on the panel |
| **Exit Application** | Click **`Exit`** in top-right, or right-click $\to$ *Exit Kya-Ray completely* |

> [!NOTE]
> Pressing `Esc` only dismisses the visible response panel. It will not unexpectedly terminate Kya-Ray while you are working in other apps.

---

## 🛠️ Diagnostics & Troubleshooting

- **Log File**: If you ever experience issues, diagnostics are saved to:
  `%LOCALAPPDATA%\Kya-Ray\kya-ray.log`
- **"Could not connect to Ollama"**:
  Make sure Ollama is open and running in your Windows system tray.
- **"Model 'llama3.2:1b' was not found"**:
  Open Command Prompt and run: `ollama pull llama3.2:1b`.

---

## 🔒 Privacy & Performance

- **Zero Cloud Transmission**: All text inference occurs 100% locally on your machine via `http://127.0.0.1:11434`.
- **Clipboard Restoration**: Your clipboard contents before triggering the shortcut are automatically preserved and restored.

