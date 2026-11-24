# Changelog

All notable changes to the Kya-Ray desktop application are documented in this file.

---

## [1.0.0-beta.4] - 2026-11-24

### What's new
- **Transactional update validation**: Added a dedicated `VALIDATING` transaction state ensuring the newly installed application completes startup handshake validation before transaction commitment.
- **Fail-safe update recovery**: Protected transaction recovery against race conditions during post-update handshake validation.
- **PID reuse and directory lock protection**: Added 64-bit Windows process start-time verification to guard against PID reuse, and prevented in-place rollback while executing within the installation directory.

### Improvements
- Resolved release-blocking post-update startup failure ("no Qt platform plugin could be initialized").
- Hardened backup lifecycle to guarantee known-good rollback files are preserved until validation succeeds.
- Added comprehensive unit and end-to-end regression suites for installer process lifecycle.

### Notes
- This is a beta release. You may encounter bugs.
- A free Groq API key is required for AI features.

---

## [1.0.0-beta.3] - 2026-11-20

### What's new
- **Enhanced creative generation**: Greatly improved response variety for creative requests (e.g., jokes, stories, poems, and creative lines) to prevent repetitive or formulaic outputs.
- **Intent-aware sampling temperature**: Tuned AI sampling parameters specifically for creative drafting (temperature 0.7) while maintaining precision and factual accuracy for code, summaries, and explanations (temperature 0.2).
- **Original & context-aware writing**: Upgraded prompt guidelines to avoid clichés, stock templates, and predictable one-liners in favor of fresh, natural phrasing.

### Improvements
- Resolved repetitive output issue on creative prompts (#13).
- Added comprehensive unit testing for intent-aware model temperature resolution and prompt variety.
- Improved cross-environment path resolution in test infrastructure.

### Notes
- This is a beta release. You may encounter bugs.
- A free Groq API key is required for AI features.

---

## [1.0.0-beta.2] - 2026-11-11

### What's new
- **In-app update checks**: Kya-Ray can now check for updates from inside the app.
- **Visual download progress**: Updates download with live progress tracking and integrity validation before installation.
- **Safer installation process**: The updater installs updates safely in the background, with automatic backup and recovery if something goes wrong.
- **Background update checks**: Update checks can now run periodically in the background so you know when a new version is ready.

### Improvements
- Improved the Windows update and installation experience.
- Added clearer update progress reporting and error handling.
- Enhanced application startup safety and recovery after an interrupted update.

### Notes
- This is a beta release. You may encounter bugs.
- A free Groq API key is required for AI features.

---

## [1.0.0-beta.1] - 2026-11-03

### What's new
- **Setup window**: Added a setup window to easily configure and test your Groq API key on first launch.
- **Secure credential storage**: Stored API keys securely in Windows Credential Manager without keeping plaintext secrets in local files.
- **Fast streaming responses**: Streaming AI responses connected to GroqCloud for low-latency answers.
- **Clipboard preservation**: Original clipboard content is preserved whenever text is captured.

### Improvements
- Packaged as a standalone Windows application with installer and portable launch scripts.
- Clean application shutdown ensuring both desktop interface and local background service stop together.

---

## [0.2.0-beta] - 2026-11-03

- Initial standalone Windows packaging.
- Added installer and launcher scripts.
- Switched AI inference backend to GroqCloud.

---

## [0.1.0-beta] - 2026-10-29

- Initial prototype release.
