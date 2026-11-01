# Kya-Ray

*A little context-aware AI desktop companion.*

Kya-Ray helps you understand and work with whatever you are looking at, right where you are.

Select something. Press **`Ctrl + Alt + Space`**. Keep going.

![Kya-Ray — product vision](assets/kya-ray-vision.png)

---

## What is Kya-Ray?

When reading documentation, reviewing code, or writing messages, you often encounter unfamiliar terms, complex code snippets, or lengthy text. Normally, you have to copy the text, open a browser, paste it into an AI chat, and switch back.

Kya-Ray streamlines this into a single keystroke:

1. **Highlight text** in any application (browser, IDE, PDF, terminal, or document).
2. **Press `Ctrl + Alt + Space`**.
3. A compact floating card appears near your cursor with a clear, concise AI answer.

- **100% Local & Private**: Runs entirely offline via [Ollama](https://ollama.com) (`llama3.2:1b`). Zero cloud transmission.
- **Zero Interruption**: Automatically captures selected text and restores your previous clipboard contents immediately.
- **Automatic Intent Inference**: Understands whether to explain, summarize, analyze code, or draft content without manual mode-switching.

---

## Four Intelligent Intents

Kya-Ray automatically determines what kind of help you need based on the highlighted context:

- **Explain** — Plain-language definitions for unfamiliar words, technical terms, and concepts with strict anti-hallucination guardrails.
- **Summarize** — Condenses long prose ($\ge 50$ words), articles, and meeting notes into 1–2 short sentences.
- **Code** — Explains code snippets and terminal commands. Deterministic static diagnostics (`ast` + `difflib`) detect package typos (e.g. `panadas` $\to$ `pandas`) without inventing errors on valid code.
- **Create** — Fulfills drafting requests directly (emails, replies, ideas) with single-output defaults and no conversational preamble (*"I'd be happy to..."*).

---

## Quickstart

### 1. Prerequisites
1. Install **Ollama for Windows** from [ollama.com](https://ollama.com/download/windows).
2. Download the recommended model (~1.3 GB) in PowerShell or Command Prompt:
   ```shell
   ollama pull llama3.2:1b
   ```

### 2. Download & Run
1. Download the latest **[v0.1.0-beta Windows release](https://github.com/dumbgesh/kya-ray/releases)** (`Kya-Ray-v0.1.0-beta-win64.zip`).
2. Extract the ZIP anywhere and double-click **`START_KYA_RAY.bat`** (or `Kya-Ray\Kya-Ray.exe`).
3. Highlight text in any application and press **`Ctrl + Alt + Space`**.

### Controls

| Action | Control |
| :--- | :--- |
| **Trigger Assistant** | Highlight text + `Ctrl + Alt + Space` |
| **Dismiss Panel** | `Esc` or click `✕` in top-right |
| **Copy Response** | Click `Copy` button |
| **Reposition** | Click and drag anywhere on the panel |
| **Exit Application** | Click `Exit` in top-right, or right-click $\to$ *Exit Kya-Ray* |

---

## Running from Source

```powershell
# Clone the repository
git clone https://github.com/dumbgesh/kya-ray.git
cd kya-ray

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run application
python prototype/main.py

# Run test suite (75 tests)
python -m unittest discover tests -v
```

---

## Tech Stack

- **Runtime & GUI**: Python 3.10+ & Tkinter (minimal light card theme, dynamic height scaling, transparent keying)
- **Global Hotkeys & Capture**: `pynput` (global Windows keyboard listener) & `pyperclip` (clipboard bridge & restore)
- **Local AI Engine**: [Ollama](https://ollama.com) REST API (`localhost:11434`) running Meta's `llama3.2:1b`
- **Packaging**: PyInstaller Windows x64 onedir standalone package

---

## Current Status & Roadmap

The current public release is **`v0.1.0-beta`** (Windows x64 portable package). We are actively developing toward **`v1.0.0`**:

- [x] Global `Ctrl + Alt + Space` shortcut detection with debouncing
- [x] Four deterministic intents with static code diagnostics and preamble cleanup
- [x] Minimal light UI panel with dynamic sizing and one-click copy button
- [x] Comprehensive automated test suite (75 verified tests)
- [ ] Response token streaming (`stream: true`) for $< 400$ ms perceived latency
- [ ] Codebase modularization into structured Python package modules
- [ ] Multi-monitor cursor positioning and native Windows system tray integration

---

## Documentation

- [Windows Beta Quickstart Guide](README_BETA.md) — Detailed setup instructions, launcher details, and troubleshooting.
- [Feature Specifications System](features/README.md) — Full specifications for core interactions, intent taxonomy, UI, and privacy.

---

## License

Open-source under the MIT License.
