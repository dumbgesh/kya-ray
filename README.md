# Kya-Ray

*A little context-aware AI desktop companion.*

Understand and work with what you're looking at, without switching between apps.

**Select. Press `Ctrl + Alt + Space`. Keep going.**

![Kya-Ray — product vision](assets/kya-ray-vision.png)

---

## What is Kya-Ray?

Ever come across something confusing while reading documentation, browsing, coding, or writing?

Instead of copying it into an AI chat, Kya-Ray lets you get help right where you are.

1. Select any text.
2. Press `Ctrl + Alt + Space`.
3. Get an AI response in a small floating panel.

Kya-Ray runs locally through [Ollama](https://ollama.com), using `llama3.2:1b`. Your selected text stays on your machine.

---

## Four ways to work

Kya-Ray automatically figures out what kind of help you need.

- **Explain** — Understand unfamiliar words, concepts, and technical terms.
- **Summarize** — Turn lengthy text into short, useful takeaways.
- **Code** — Understand code and commands, with basic typo and syntax diagnostics.
- **Create** — Draft emails, replies, ideas, and other content.

No need to select a mode. Just select text and ask.

---

## Getting Started

### 1. Install Ollama

Download [Ollama for Windows](https://ollama.com/download/windows).

Then open PowerShell and run:

```powershell
ollama pull llama3.2:1b
```

### 2. Download Kya-Ray

Download the [latest Windows release](https://github.com/dumbgesh/kya-ray/releases).

Extract the ZIP and run `START_KYA_RAY.bat` (or `Kya-Ray\Kya-Ray.exe`).

That's it. Select some text and press `Ctrl + Alt + Space`.

### Controls

| Action | Shortcut |
|---|---|
| Open Kya-Ray | Select text + `Ctrl + Alt + Space` |
| Dismiss panel | `Esc` or `✕` |
| Copy response | `Copy` button |
| Move panel | Click and drag |
| Exit | `Exit` button or right-click menu |

---

## Running from Source

```powershell
git clone https://github.com/dumbgesh/kya-ray.git
cd kya-ray

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

python prototype/main.py

# Run tests
python -m unittest discover tests -v
```

---

## Built With

- **Python & Tkinter** — Application and interface.
- **pynput** — Global keyboard shortcuts.
- **pyperclip** — Selected-text capture and clipboard handling.
- **Ollama & Llama 3.2 1B** — Local AI inference.
- **PyInstaller** — Windows application packaging.

---

## Where We Are

The latest public release is **`v0.1.0-beta`** for Windows x64.

We're working towards **`v1.0.0`**.

### What's working

- [x] Global keyboard shortcut.
- [x] Four automatic intents.
- [x] Floating response panel.
- [x] Clipboard restoration.
- [x] Code diagnostics.
- [x] Automated test suite (75 verified tests).

### What's next

- [ ] Faster, streamed responses.
- [ ] A more modular codebase.
- [ ] Better multi-monitor support.
- [ ] Windows system tray integration.

---

## More Documentation

- [Windows Quickstart & Troubleshooting](README_BETA.md)
- [Feature Specifications](features/README.md)

---

## License

Kya-Ray is open-source software licensed under the [MIT License](LICENSE).
