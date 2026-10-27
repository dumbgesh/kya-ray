# Feature 04: AI Response Engine (Local Inference & Model Orchestration)

## Status
`In Progress`

---

## Purpose
The AI Response Engine coordinates communication with local AI language models. It transforms captured user context and inferred task intents into structured generation requests, executes non-blocking local inference via Ollama, handles failures safely, and returns the generated content alongside telemetry metadata.

---

## Core Responsibilities
1. **Input Ingestion**: Ingests captured text and optional intent metadata from the context capture bridge.
2. **Prompt Orchestration**: Constructs structured prompts tailored to the active intent while suppressing model verbosity and preventing hallucinated facts.
3. **Local Inference Execution**: Communicates with the local Ollama background service via standard HTTP protocols.
4. **Latency & Token Budgeting**: Enforces strict timeout boundaries and generation limits to keep response latency low.
5. **Fault Containment**: Intercepts model missing (404), connection refused, timeout, and empty response errors, translating them into actionable user messages.
6. **Telemetry Extraction**: Captures server-side execution metrics (`load_duration`, `eval_duration`, `eval_count`) without logging private prompt or response content.

---

## Current Implementation (Verified in Codebase)

### Architecture
Implemented in [`prototype/main.py`](../prototype/main.py#L129-L185) via `request_ai_explanation(text)` and `sanitize_ollama_metrics()`.

### Technical Parameters
- **Target Endpoint**: `http://127.0.0.1:11434/api/generate` (`OLLAMA_API_URL`)
- **Default Model**: `llama3.2:1b` (compact 1.3 GB local model)
- **Library**: Python standard library `urllib.request` and `json` (zero third-party networking dependencies).
- **Protocol**: HTTP POST with JSON body.
- **Request Timeout**: 30 seconds (`REQUEST_TIMEOUT_SECONDS = 30`).
- **Streaming Setting**: `stream: False` (waits for full response payload before returning).
- **Keep-Alive Setting**: **Omitted** in the current prototype (relies on Ollama's default 5-minute idle unload policy).
- **Generation Options**: Unconfigured (defaults to Ollama defaults for temperature `~0.8` and unbounded `num_predict`).

### Request Payload Structure
```python
payload = {
    "model": "llama3.2:1b",
    "prompt": (
        "Explain the following selected text concisely and in simple, beginner-friendly terms "
        f"(2 to 3 sentences max):\n\n\"{text.strip()}\""
    ),
    "stream": False,
}
```

### Return Signature & Thread Safety
`request_ai_explanation()` returns a 3-tuple:
```python
(success: bool, content: str, metrics: dict | None)
```
- If successful: `(True, explanation_text, numeric_metrics_dict)`
- If failed: `(False, friendly_error_message, None)`

There is **zero shared mutable state**. Each worker thread holds its own response and metrics directly on the call stack, ensuring complete thread safety across concurrent or rapid hotkey invocations.

### Verified Error Containment

| Error Condition | Handled In Code | Resulting User Notification |
| :--- | :--- | :--- |
| **HTTP 404 (Model Not Found)** | Yes (`urllib.error.HTTPError.code == 404`) | *"Model 'llama3.2:1b' was not found in Ollama. Run 'ollama pull llama3.2:1b'."* |
| **Connection Refused (Ollama Down)** | Yes (`urllib.error.URLError`) | *"Could not connect to Ollama at http://127.0.0.1:11434. Please ensure the Ollama app is running."* |
| **Network / Compute Timeout** | Yes (`TimeoutError`) | *"Request timed out after 30s waiting for Ollama to respond."* |
| **Empty Model Output** | Yes (`parsed_json.get("response", "").strip() == ""`) | *"Ollama returned an empty response."* |
| **Generic Exception** | Yes (`except Exception as error`) | Formatted diagnostic error string without crashing the UI. |

---

## Telemetry & Metrics Extraction
When an HTTP 200 response is received, the engine extracts the following numeric fields from the response JSON:
- `total_duration` (server total in nanoseconds)
- `load_duration` (model load into RAM/VRAM)
- `prompt_eval_duration` (prompt processing time)
- `eval_duration` (token generation duration)
- `prompt_eval_count` (prompt token count)
- `eval_count` (generated token count)

The helper `sanitize_ollama_metrics()` enforces that only non-negative numbers are retained, completely stripping any text, prompt, or response fields before passing metrics to telemetry.

---

## Current Implementation vs. Desired Architecture

| Capability | Current Prototype | Target Engine Specification |
| :--- | :--- | :--- |
| **Prompt Routing** | Single hardcoded explanation prompt. | Multi-intent prompt registry mapped to [03-hyphen-features.md](03-hyphen-features.md). |
| **Output Streaming** | Blocking (`stream: False`), blocks until completion. | Token streaming (`stream: True`) to achieve instantaneous time-to-first-token in the UI. |
| **Token Budgeting** | Unbounded `num_predict`. | Explicit `num_predict` caps per intent (e.g., 45 tokens for explain, 120 for summarize). |
| **Model Residency** | Default `keep_alive` (unloads after 5m). | Explicit `keep_alive: "10m"` or configurable background residency. |
| **Sampling Parameters** | Default temperature. | Intent-specific temperature (e.g., `0.2` for code, `0.7` for creative writing). |

---

## Acceptance Criteria
- [x] Communicates with local Ollama service without external internet dependencies.
- [x] Handles service downtime, missing models, and request timeouts gracefully.
- [x] Dispatches requests non-blockingly on background threads.
- [x] Extracts and sanitizes numeric server telemetry.
- [ ] Support token streaming directly into the floating bubble UI (`Planned`).
- [ ] Dynamically inject prompt templates matching the inferred intent (`Planned`).
- [ ] Configure `keep_alive` and `num_predict` to maintain tight latency budgets (`Planned`).

---

## Edge Cases
- **Cold Model Eviction**: If Ollama has been idle for >5 minutes, model weights must reload from disk, causing an initial request delay of ~10–12 seconds.
- **VRAM / RAM Saturation**: If other large applications consume GPU memory, Ollama may fall back to CPU inference, significantly reducing generation speed.
- **Model Truncation**: When strict token caps (`num_predict`) are applied, generation can cut off mid-sentence unless guided by appropriate prompt stop-sequences.

---

## Dependencies
- **External Software**: Ollama daemon (`ollama.exe`) running locally on port 11434.
- **Model Weights**: `llama3.2:1b` (1.3 GB local weight file).
- **Subsystems**:
  - [02-context-capture.md](02-context-capture.md) (provides input text).
  - [03-hyphen-features.md](03-hyphen-features.md) (supplies intent constraints).
  - [05-floating-bubble-ui.md](05-floating-bubble-ui.md) (receives response updates).
  - [06-performance-and-reliability.md](06-performance-and-reliability.md) (measures engine latency).

---

## Open Questions
- **Open question**: Should the engine switch to streaming responses (`stream: True`) immediately, or does progressive Tkinter text injection create UI flickering?
- **Open question**: Should Kya-Ray support alternative local backends (such as llama.cpp or ONNX Runtime directly via ctypes) to avoid the dependency on an external Ollama installation?
