# Feature 08: Product Roadmap (Prioritized Development Stages)

## Status
`Planned`

---

## Purpose
The Product Roadmap outlines the phased technical progression for transforming the Kya-Ray prototype into a polished, resilient, and performant context-aware desktop companion. It organizes development into logical, sequential stages with clear prerequisites, technical dependencies, and measurable completion criteria.

> [!NOTE]
> **Proposed Stages**: The stages described below represent proposed architectural and engineering progression, not binding commercial commitments. Each stage builds strictly on verified capabilities established in previous stages.

---

## Roadmap Overview

```
Stage 1: Core Flow Stabilization
   │
Stage 2: Latency & Budget Measurement
   │
Stage 3: Core 8 Hyphen Intents Definition
   │
Stage 4: Automated Intent Inference
   │
Stage 5: UI Interaction Refinements
   │
Stage 6: Reliability & Privacy Hardening
   │
Stage 7: Codebase Modularization
   │
Stage 8: Architecture Scaling Evaluation
   │
Stage 9: Release-Ready Distribution
```

---

## Detailed Stages

### Stage 1: Stabilize Existing Activation, Capture, and Response Flow
* **Goal**: Ensure the fundamental shortcut -> capture -> explain -> render loop is 100% stable and reproducible on standard Windows environments.
* **Key Tasks**:
  - Audit and fix keyboard modifier edge cases (e.g., sticky modifiers on quick key combinations).
  - Verify clean clipboard restoration across all tested software (VS Code, Chrome, Word, Notepad).
  - Ensure background threads terminate cleanly upon application exit without lingering locks.
* **Dependencies**: [01-core-interaction.md](01-core-interaction.md), [02-context-capture.md](02-context-capture.md).
* **Completion Criteria**: 20 consecutive manual activations with text highlighted across 4 different applications without a single crash, skipped capture, or scrambled clipboard.

---

### Stage 2: Measure and Improve Latency (Cold-Start & Warm-Response)
* **Goal**: Bring warm end-to-end response latency down from ~5.0s toward `< 2.5s` and establish predictable cold-start handling.
* **Key Tasks**:
  - Run scientific one-variable-at-a-time (OVAT) benchmarks using `pipeline_profiler.py`.
  - Benchmark impact of `num_predict` token capping (e.g. 40, 50, 60 tokens).
  - Benchmark impact of `keep_alive` values (`"10m"`, `"15m"`) on model retention.
  - Implement token streaming (`stream: True`) to deliver time-to-first-token in `< 400ms`.
* **Dependencies**: [04-ai-response-engine.md](04-ai-response-engine.md), [06-performance-and-reliability.md](06-performance-and-reliability.md).
* **Completion Criteria**: Warm response time delivers first visible token in `< 500ms` and finishes full generation in `< 2.5s` on baseline hardware.

---

### Stage 3: Define and Test the Eight Core Hyphen Intents
* **Goal**: Implement and evaluate structured prompt templates for all 8 core intents (`-explain`, `-summarize`, `-compare`, `-code`, `-create`, `-complete`, `-suggest`, `-rewrite`).
* **Key Tasks**:
  - Create prompt catalog mapping each intent to system instructions and output format constraints.
  - Test intent quality against a fixed evaluation suite of sample texts.
  - Enforce anti-hallucination constraints ensuring the model never invents missing facts.
* **Dependencies**: [03-hyphen-features.md](03-hyphen-features.md), [04-ai-response-engine.md](04-ai-response-engine.md).
* **Completion Criteria**: Automated test harness validating that each of the 8 intents produces structurally valid, well-bounded outputs for benchmark inputs.

---

### Stage 4: Improve Intent Inference & Ambiguous-Input Handling
* **Goal**: Automatically route arbitrary user selections to the appropriate intent without requiring manual mode selection.
* **Key Tasks**:
  - Design a fast, lightweight classification heuristic combining syntax detection (regex/code detection) with local LLM classification.
  - Build fallback logic that routes low-confidence selections to neutral explanations or concise clarification options.
  - Ensure short text fragments (e.g. single ambiguous words) trigger cautious definitions rather than unwarranted assumptions.
* **Dependencies**: [03-hyphen-features.md](03-hyphen-features.md).
* **Completion Criteria**: Intent classifier achieves >85% accuracy on a curated 100-sample desktop selection test suite.

---

### Stage 5: Improve Floating Bubble UI Interaction and Error States
* **Goal**: Transform the read-only Tkinter bubble into a polished, responsive desktop HUD.
* **Key Tasks**:
  - Add Markdown formatting support for bold text, bulleted lists, and syntax-highlighted code blocks.
  - Implement dynamic window sizing (bubble auto-sizes height to fit short answers without scrollbars).
  - Add one-click "Copy to Clipboard" button and subtle action chips.
  - Refine error notifications with specific troubleshooting links (e.g. "Ollama not running", "Model missing").
* **Dependencies**: [05-floating-bubble-ui.md](05-floating-bubble-ui.md).
* **Completion Criteria**: Markdown renders cleanly with code blocks; window height adapts smoothly to content.

---

### Stage 6: Strengthen Reliability and Privacy Safeguards
* **Goal**: Eliminate data leakage risks and harden system resilience.
* **Key Tasks**:
  - Remove plain-text printing of captured selections from application console logs.
  - Investigate clipboard exclusion flags (`ExcludeClipboardContentFromMonitorProcessing`) to prevent pollution of Windows Clipboard History (`Win + V`).
  - Add graceful recovery from network socket drops, Ollama server restarts, and OS sleep/wake cycles.
* **Dependencies**: [02-context-capture.md](02-context-capture.md), [07-privacy-and-security.md](07-privacy-and-security.md).
* **Completion Criteria**: Third-party clipboard history tools do not retain temporary capture buffers; zero user text written to logs.

---

### Stage 7: Modularize the Prototype
* **Goal**: Transition from monolithic single-file prototype (`prototype/main.py`) into clean, maintainable Python package architecture.
* **Key Tasks**:
  - Extract modules: `kya_ray/core/hotkey.py`, `kya_ray/capture/clipboard.py`, `kya_ray/engine/ollama.py`, `kya_ray/ui/bubble.py`.
  - Establish unit test coverage for each subsystem with mocked external OS and Ollama interfaces.
  - Maintain backward compatibility aliases for existing prototype scripts.
* **Dependencies**: Stages 1 through 6.
* **Completion Criteria**: Monolithic `main.py` replaced by modular package passing comprehensive test suite with 100% passing tests.

---

### Stage 8: Evaluate a Production Architecture (Only When Justified)
* **Goal**: Assess whether transitioning beyond Python/Tkinter (e.g., PySide6/Qt, Rust/Tauri, or C#/WinUI) is necessary based on concrete user needs.
* **Key Tasks**:
  - Profile memory footprint, startup time, and installer bundle size of Python runtime vs. compiled binaries.
  - Determine if multi-monitor DPI scaling and hardware-accelerated animations justify a heavier native UI framework.
* **Dependencies**: Stage 7.
* **Completion Criteria**: Written Architecture Decision Record (ADR) detailing quantitative trade-offs before any rewrite is approved.

---

### Stage 9: Prepare Release-Ready Demo and Distribution
* **Goal**: Package Kya-Ray for friction-free local desktop installation.
* **Key Tasks**:
  - Package standalone executable or installer (e.g., PyInstaller, Inno Setup) with embedded or auto-configured Ollama bridge.
  - Prepare animated demo recordings and quickstart documentation.
  - Provide automated prerequisite checks (verifying Ollama availability and model download status).
* **Dependencies**: Stages 1 through 8.
* **Completion Criteria**: New user can download, install, and successfully trigger Kya-Ray in under 3 minutes on a clean Windows machine.

---

## Acceptance Criteria
- [x] Clear roadmap stages documented with sequential progression and prerequisites.
- [x] Measurable completion criteria defined for every development phase.
- [x] Clear boundary established preventing premature full-application rewrites.

---

## Open Questions
- **Open question**: At what development stage should multi-platform support (macOS accessibility APIs and Linux X11/Wayland portals) be considered?
- **Open question**: Should the eventual packaging include an embedded runtime for Ollama, or remain an companion app expecting a system-installed Ollama?
