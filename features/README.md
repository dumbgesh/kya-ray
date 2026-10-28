# Kya-Ray Feature Documentation

Welcome to the **Kya-Ray Feature Documentation System**. This directory contains structured, maintainable Markdown specifications for Kya-Ray's product features, design decisions, and technical capabilities.

---

## Purpose of this Directory

1. **Single Source of Truth**: Establishes clear definitions of intended system behaviour, current prototype capabilities, and acceptance criteria.
2. **Guidance for AI Coding Agents**: Provides AI coding assistants with verifiable behavioral boundaries before modifying code, preventing hallucinations and accidental regressions.
3. **Open Contributor Clarity**: Helps human developers understand how Kya-Ray functions end-to-end, what is already working, and what decisions are pending.

---

## Status Classification

Every feature specification in this directory uses one of five standardized status labels. **Status labels must always reflect verified repository behaviour, never unverified assumptions or forward-looking hopes.**

| Status Label | Definition |
| :--- | :--- |
| **`Implemented`** | Verified and covered by code in the repository; functional and tested. |
| **`In Progress`** | Working prototype code exists in the repository, but key capabilities, error handling, or refinements remain incomplete. |
| **`Planned`** | Conceptually defined, specified, and scheduled, but no functional code exists in the repository yet. |
| **`Experimental`** | Prototype or diagnostic code exists for benchmarking/validation, but may change or be refactored significantly. |
| **`Needs Decision`** | Architecture, UX, or design trade-offs require stakeholder decision before implementation can begin. |

---

## Feature Specifications Index

| ID | Document | Title | Current Status | Description |
| :--- | :--- | :--- | :--- | :--- |
| **01** | [01-core-interaction.md](01-core-interaction.md) | **Core Interaction** | `In Progress` | Global keyboard shortcut detection (`Ctrl + Shift + J`), activation lifecycle, and clean application shutdown. |
| **02** | [02-context-capture.md](02-context-capture.md) | **Context Capture** | `In Progress` | Non-blocking text capture from external applications via temporary clipboard bridge and clipboard restoration. |
| **03** | [03-hyphen-features.md](03-hyphen-features.md) | **Hyphen Features (Intents)** | `In Progress` | Automatic context-based intent classification system (`-explain`, `-summarize`, `-code`, `-create`, etc.). |
| **04** | [04-ai-response-engine.md](04-ai-response-engine.md) | **AI Response Engine** | `In Progress` | Local LLM inference via Ollama (`llama3.2:1b`), request lifecycle, prompt structure, and error containment. |
| **05** | [05-floating-bubble-ui.md](05-floating-bubble-ui.md) | **Floating Bubble UI** | `In Progress` | Always-on-top, draggable desktop speech-bubble window anchored to mouse cursor context with state indicators. |
| **06** | [06-performance-and-reliability.md](06-performance-and-reliability.md) | **Performance & Reliability** | `Experimental` | End-to-end stage telemetry, UDP latency profiler, cold vs. warm model runs, and benchmarking methodologies. |
| **07** | [07-privacy-and-security.md](07-privacy-and-security.md) | **Privacy & Security** | `In Progress` | Local-only execution boundaries, clipboard data handling, strict telemetry sanitization, and data isolation. |
| **08** | [08-roadmap.md](08-roadmap.md) | **Product Roadmap** | `Planned` | Prioritized 9-stage engineering roadmap outlining prerequisites, dependencies, and completion criteria. |

---

## Rules for AI Coding Agents

When interacting with this codebase, all AI coding agents must adhere to the following rules:

1. **Read Before Writing**: Before modifying any application code, read the relevant feature document in `features/` to understand intended constraints, acceptance criteria, and edge cases.
2. **Never Claim Planned Work is Implemented**: If a feature is marked `Planned` or `Needs Decision`, do not present it to users or documentation as functional unless you have implemented and tested it.
3. **Preserve Boundaries**: Keep feature implementations modular. Do not introduce tight coupling between intent classification, UI rendering, and transport telemetry.
4. **Update Documentation Upon Modification**: Whenever your changes alter a feature's behaviour, interface, or status, update the corresponding specification document immediately.
5. **Record Open Questions**: If a design decision or edge case cannot be definitively resolved from existing code or instructions, document it explicitly under `Open questions` rather than inventing an implementation.
