# Kya-Ray

A little AI companion for your Windows desktop.

Ever come across something you don't understand while reading, coding, or browsing?

Usually, you'd copy it, open another tab, paste it into an AI chat, and come back.

Kya-Ray makes that easier. Select text, press a shortcut, and get help without leaving what you're doing.

**Select. Press `Ctrl + Alt + Space`. Keep going.**

---

## Getting started

1. Download the latest Windows release from [GitHub Releases](https://github.com/dumbgesh/kya-ray/releases).
2. Extract the ZIP file.
3. Run `Install-Kya-Ray.bat` to install, or use `START_KYA_RAY.bat` to run portably.
4. Enter your [Groq API key](https://console.groq.com/keys) when prompted.
5. Select text in any application and press `Ctrl + Alt + Space`.

---

## What can it do?

- **Explain** unfamiliar concepts, acronyms, and technical terms.
- **Summarize** longer articles, messages, and documents.
- **Understand code** and help investigate problems and fixes.
- **Create** drafts, replies, and ideas on the spot.

Just select what you're working with. Kya-Ray figures out the kind of help you need.

---

## Shortcuts and controls

| Action | Control |
| :--- | :--- |
| **Open Kya-Ray** | Highlight text + `Ctrl + Alt + Space` |
| **Dismiss** | `Esc` |
| **Copy response** | `Ctrl + C` (when window is focused) or click `Copy` |
| **Move window** | Click and drag the window |
| **Context menu** | Right-click the assistant window |
| **Exit** | Right-click $\to$ *Exit Kya-Ray* |

---

## Running from source

You'll need Windows, Python 3.10+, and a free Groq API key.

```powershell
git clone https://github.com/dumbgesh/kya-ray.git
cd kya-ray
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Add your Groq API key to `.env`, then run:

```powershell
python desktop/app.py
```

---

## Updates

Kya-Ray includes an in-app updater. Open the assistant's context menu (right-click) and choose **Check for Updates...** to look for a newer release. Update checks can also happen automatically in the background.

---

## Privacy

Kya-Ray uses a local backend and Groq for AI processing. Selected text is sent to Groq only when you request an AI response. Avoid selecting sensitive information.

---

## Help and feedback

- [User Guide](docs/guides/USER_GUIDE.md)
- [Troubleshooting](docs/guides/TROUBLESHOOTING.md)
- [Report an issue](https://github.com/dumbgesh/kya-ray/issues)
- [Changelog](CHANGELOG.md)

---

## License

Kya-Ray is open source under the [MIT License](LICENSE).
