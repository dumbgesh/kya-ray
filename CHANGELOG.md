# Changelog - Kya-Ray

All notable changes to the Kya-Ray desktop application are documented in this file.

---

## [v1.0.0-beta.1] - 2026-11-03

### Added
- **Integrated First-Launch Setup Window**: Native PySide6 setup window allowing users to enter and verify their Groq API key graphically on first run without touching `.env` or opening a terminal.
- **Show/Hide Key Toggle**: Masked password field with dynamic Show/Hide toggle.
- **Secure Windows Credential Manager Storage**: Integrated with Windows `advapi32.dll` (`CredWriteW`/`CredReadW`), encrypting credentials via the active Windows user profile's DPAPI master key.
- **Zero Plaintext Key Requirement**: Application runs fully self-contained without requiring `.env` files on disk.
- **Pure ASGI DNS Rebinding Protection**: Implemented `HostValidationMiddleware` to reject untrusted host headers and guard against DNS rebinding attacks while avoiding `BaseHTTPMiddleware` overhead.
- **Credential Replacement Security**: Settings dialog keeps the input field blank and preserves the old credential if validation fails.
- **Clean Application Shutdown**: Ensures both the PySide6 UI and the owned FastAPI backend terminate cleanly with exit code `0`.
- **Automated Regression Suite**: Expanded automated test suite to 296 passing tests with native `faulthandler_timeout` protection.

### Improved
- **Real-Time Streaming Performance**: Live SSE streaming connected to GroqCloud's `qwen/qwen3.8-27b` model with sub-second response latency.
- **Clipboard Preservation**: Guaranteed restoration of original clipboard contents after selection capture.
- **Self-Healing Backend Lifecycle**: Background process manager automatically starts, health-checks, and cleans up local services.
- **Windows Packaging**: Self-contained PyInstaller distribution with clean installer and uninstaller scripts registering in Windows Add/Remove Programs.

---

## [v0.2.0-beta] - 2026-11-03
- Initial controlled packaging with PyInstaller.
- Added `START_KYA_RAY.bat`, `Install-Kya-Ray.bat`, and `Configure-API-Key.bat`.
- Migrated LLM backend to GroqCloud (`qwen/qwen3.8-27b`).

---

## [v0.1.0-beta] - 2026-10-29
- Initial Tkinter prototype and local LLM integration.

