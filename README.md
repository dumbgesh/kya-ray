# Kya-Ray

*A context-aware AI desktop companion for Windows.*

Understand and work with what you're looking at, without switching between apps.

**Select. Press `Ctrl + Alt + Space`. Keep going.**

![Kya-Ray — product vision](assets/kya-ray-vision.png)

---

## What is Kya-Ray?

Ever come across something confusing while reading documentation, browsing, coding, or writing?

Instead of copying text into an external browser chat, Kya-Ray brings AI assistance directly to your workflow in a single keystroke:

1. **Highlight text** in any application (browser, IDE, PDF, terminal, or document).
2. **Press `Ctrl + Alt + Space`**.
3. A compact floating card appears near your cursor with a clear, concise AI answer streamed in real time.

---

## Four Intelligent Intents

Kya-Ray automatically determines what kind of help you need without manual mode switching:

- **Explain (`EXPLAIN`)** — Clear, objective definitions for unfamiliar words, technical terms, and complex concepts.
- **Summarize (`SUMMARY`)** — Condenses long articles, status reports, email threads, and meeting notes into 1–2 crisp sentences with key action items.
- **Code (`CODE`)** — Rigorous code analysis, execution flow inspection, syntax/logic defect diagnosis, and concrete fixes without hallucinating phantom warnings on valid code.
- **Create (`CREATE`)** — Fulfills drafting requests directly (emails, replies, ideas) without conversational preamble (*"I'd be happy to help..."*).

---

## System Architecture

```
┌────────────────────────────────────────────────────────┐
│                   Active Windows App                   │
│         (VS Code, Browser, PDF, Terminal, etc.)        │
└──────────────────────────┬─────────────────────────────┘
                           │ 1. User highlights text & presses Ctrl+Alt+Space
                           ▼
┌────────────────────────────────────────────────────────┐
│               Kya-Ray Desktop (PySide6)                │
│  - HotkeyListener: Global Windows keyboard hook        │
│  - SelectionCapture: Win32 clipboard bridge & restore  │
│  - Floating Card: Dynamic height sizing & smooth stream│
│  - Persistent BackendClient: HTTP connection pool      │
└──────────────────────────┬─────────────────────────────┘
                           │ 2. POST /api/v1/ai/stream (SSE)
                           ▼
┌────────────────────────────────────────────────────────┐
│            Kya-Ray Local Backend (FastAPI)             │
│  - Bound to 127.0.0.1 (Loopback only)                  │
│  - DNS Rebinding Protection (Host header validation)   │
│  - Lifecycle bound via Windows Job Object              │
│  - Error Masking: Strips API keys & Bearer tokens      │
└──────────────────────────┬─────────────────────────────┘
                           │ 3. HTTPS Async Streaming
                           ▼
┌────────────────────────────────────────────────────────┐
│             GroqCloud Accelerated Inference            │
│  - Model: qwen/qwen3.8-27b                             │
│  - High-speed token generation with real-time SSE      │
└────────────────────────────────────────────────────────┘
```

---

## Quickstart (Beta Release)

1. Download **`Kya-Ray-v1.0.0-beta1-win64.zip`** from releases.
2. Extract the archive.
3. Run **`Install-Kya-Ray.bat`** (or run portably with `START_KYA_RAY.bat`).
4. On first launch, the native setup window opens. Enter your free [Groq API Key](https://console.groq.com/keys) and click **Connect and continue**.
5. Select text in any window and press **`Ctrl + Alt + Space`**!

### Controls

| Action | Control |
| :--- | :--- |
| **Summon Assistant** | Highlight text + `Ctrl + Alt + Space` |
| **Dismiss Window** | `Esc` or `Ctrl + W` |
| **Copy Response** | `Ctrl + C` (when window is focused) or click `Copy` |
| **Reposition** | Click and drag the header bar |
| **Resize** | Drag the bottom-right grip handle (`:::`) |
| **Exit Kya-Ray** | Right-click the card $\to$ *Exit Kya-Ray* |

---

## Running from Source

### Prerequisites
- Python 3.10+ (64-bit on Windows)
- Free Groq API Key from [console.groq.com/keys](https://console.groq.com/keys)

### Setup & Run
```powershell
# Clone the repository
git clone https://github.com/dumbgesh/kya-ray.git
cd kya-ray

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install runtime and development dependencies
pip install -r requirements.txt

# Configure your Groq API key
copy .env.example .env
# Edit .env and set GROQ_API_KEY=gsk_...

# Run the desktop application (auto-starts local backend)
python desktop/app.py

# Alternatively, run backend standalone for development:
python -m backend.main
```

---

## Running the Automated Test Suite

Kya-Ray includes 296 comprehensive regression tests covering unit logic, integration pipelines, UI state transitions, packaging, and security protections:

```powershell
# Run the full test suite
pytest

# Run with verbose output
pytest -v

# Run specific test modules
pytest tests/test_round2_product_quality.py
pytest tests/test_intent_intelligence_overhaul.py
pytest tests/test_backend_client_and_streaming.py
```

---

## Documentation

Comprehensive guides and technical documentation are available in [`docs/`](docs/):

- **[User Guide](docs/guides/USER_GUIDE.md)** — Installation, daily workflows, intent handling, and settings.
- **[Troubleshooting](docs/guides/TROUBLESHOOTING.md)** — Diagnostic steps for shortcuts, credentials, and network connectivity.
- **[Beta Testing Guide](docs/guides/BETA_TESTING_GUIDE.md)** — Structured test scenarios for beta testers.
- **[Architecture & Design](docs/architecture/understanding.md)** — Deep dive into Kya-Ray's client-server architecture and data flow.
- **[Feature Specifications](docs/architecture/features/README.md)** — Detailed technical specifications for all core subsystem interactions.
- **[Changelog](CHANGELOG.md)** — Release history and notable changes.

---

## Packaging Standalone Distribution

Kya-Ray uses PyInstaller to produce a self-contained, onedir Windows distribution bundling the PySide6 desktop GUI and embedded FastAPI backend:

```powershell
# Build standalone distribution
pyinstaller kya-ray.spec --noconfirm

# Output is generated in:
#   dist\Kya-Ray\Kya-Ray.exe
```

---

## Security & Privacy

- **Zero User Text Logging:** Selected text, prompts, and model responses are strictly held in volatile memory and never logged to disk.
- **Loopback Backend:** The local backend binds exclusively to `127.0.0.1` and includes Host header validation to eliminate DNS rebinding attacks.
- **Backend-Only Credentials:** API keys are never bundled, never transmitted to the frontend GUI, and masked from all error details.
- **Clipboard Safety:** Previous user clipboard contents are automatically recorded and restored immediately after selection capture.

---

## License

Kya-Ray is open-source software licensed under the [MIT License](LICENSE).
