# Feature 06: Performance & Reliability (Instrumentation, Benchmarks & SLOs)

## Status
`Experimental`

---

## Purpose
The Performance and Reliability system establishes high-precision diagnostic observability across Kya-Ray's end-to-end pipeline. It enables developers to measure each boundary, isolate bottlenecks (such as model load times vs. generation duration), and run reproducible, one-variable-at-a-time optimization experiments while strictly preserving user privacy.

---

## Intended Performance Boundaries & Latency Objectives

Kya-Ray aims for high responsiveness. The pipeline is decomposed into six sequential stages:

```
[Hotkey Detected]
       │  Stage 1: Worker Thread Startup (< 2ms)
       ▼
[Activation Started]
       │  Stage 2: Clipboard Text Capture (~100ms)
       ▼
[Text Capture Completed]
       │  Stage 3: Pre-Request Setup (< 1ms)
       ▼
[Ollama Request Started]
       │  Stage 4: Ollama Local Inference (Target: < 2000ms warm)
       ▼
[Ollama Response Received]
       │  Stage 5: UI Queue Push (< 1ms)
       ▼
[UI Update Queued]
       │  Stage 6: UI Queue Poll & Render (< 50ms)
       ▼
[Answer Displayed]
```

### Ideal Performance Targets (Service Level Objectives)
- **Total Warm Latency**: `< 2.5 seconds` end-to-end from hotkey press to complete rendered explanation.
- **Time to First Visible Feedback**: `< 120 ms` (bubble appears showing "Thinking..." status while inference runs).
- **Clipboard Bridge Overhead**: `< 110 ms` for complete capture and clipboard restoration.
- **UI Redraw Overhead**: `< 60 ms` between queue push and final widget idletask flush.

---

## Current Diagnostic Instrumentation (Verified in Codebase)

### Telemetry Socket Architecture
Implemented in [`prototype/main.py`](../prototype/main.py#L40-L105) and [`prototype/pipeline_profiler.py`](../prototype/pipeline_profiler.py).
- **Communication Protocol**: Local UDP datagram socket on `127.0.0.1:49999`.
- **Zero Overhead**: Fire-and-forget non-blocking UDP emissions taking `< 0.02ms` per milestone.
- **Milestone Events Tracked**:
  1. `hotkey_detected`
  2. `activation_started`
  3. `text_capture_started`
  4. `text_capture_completed`
  5. `ollama_request_started`
  6. `ollama_response_received` (includes numeric server metrics)
  7. `ui_update_queued`
  8. `answer_displayed`

### Telemetry Privacy Boundaries
The profiler packet schema is strictly enforced:
```json
{
  "run_id": 1,
  "event": "ollama_response_received",
  "ts": 12345.6789,
  "error": null,
  "metrics": {
    "total_duration": 15751070000,
    "load_duration": 13820120000,
    "prompt_eval_duration": 210450000,
    "eval_duration": 1720500000,
    "prompt_eval_count": 18,
    "eval_count": 24
  }
}
```
**Strict Privacy Guarantee**: Zero user text, zero prompt strings, and zero generated answers are ever sent across the socket. The whitelist `ALLOWED_METRIC_KEYS` ensures only numeric telemetry reaches the profiler.

---

## Empirical Benchmark Baseline (Recorded October 2026)

> [!WARNING]
> **Empirical Snapshot — Not a Permanent Guarantee**: The following figures represent actual measurements captured on an Intel 13th Gen desktop running Windows 11 with Ollama v0.40.10 and model `llama3.2:1b`. Performance will vary based on CPU/GPU hardware, background load, and model architecture.

### Benchmark Run Breakdown (3 Sequential Inferences)

```text
========================================================================
  KYA-RAY V7 PIPELINE BENCHMARK SUMMARY (3 RUNS)
========================================================================
  Stage / Metric                     | Run 1    | Run 2    | Run 3    |   Average
  --------------------------------------------------------------------
  Stage 1: Worker Thread Startup     |    1.1ms |    1.0ms |    1.0ms |     1.0ms
  Stage 2: Clipboard Text Capture    |  104.2ms |  103.8ms |  104.1ms |   104.0ms
  Stage 3: Pre-Request Setup         |    0.2ms |    0.2ms |    0.2ms |     0.2ms
  Stage 4: Ollama Local Inference    | 15820.5ms| 4920.1ms | 5010.4ms |  8583.7ms
  Stage 5: UI Queue Push             |    0.1ms |    0.1ms |    0.1ms |     0.1ms
  Stage 6: UI Queue Poll & Render    |   14.2ms |   12.1ms |   11.8ms |    12.7ms
  Unaccounted Gaps                   |    0.1ms |    0.1ms |    0.1ms |     0.1ms
  --------------------------------------------------------------------
  TOTAL PIPELINE LATENCY             | 15940.4ms| 5037.3ms | 5127.7ms |  8701.8ms
  --------------------------------------------------------------------
  Ollama Server-Side Timing Telemetry (Internal):
  - load_duration                    | 10890.2ms|    0.0ms |    0.0ms |  3630.1ms
  - prompt_eval_duration             |   180.4ms|  172.1ms |  175.0ms |   175.8ms
  - eval_duration                    |  4740.1ms| 4735.0ms | 4820.2ms |  4765.1ms
  - total_duration (server)          | 15810.7ms| 4907.1ms | 4995.2ms |  8571.0ms
  - eval_count (tokens)              |       59 |       60 |       61 |      60.0
  - Generation Speed                 |  12.45t/s|  12.67t/s|  12.65t/s|   12.59t/s
========================================================================
  * Cold Run 1 Total Latency: 15940.4 ms (15.94 s) — Model load: 10.89 s
  * Warm Average Total (2+):   5082.5 ms ( 5.08 s)
  * Warm Generation Speed:     12.66 tokens/second
```

### Analysis of the Baseline
1. **Cold-Start Penalty**: The first run took ~15.94 seconds, with **10.89 seconds (68%)** spent exclusively on loading model weights from disk/storage into memory (`load_duration`).
2. **Warm-Run Ceiling**: Subsequent warm runs executed in **~5.08 seconds**. Model loading dropped to near zero, but generation duration remained ~4.75 seconds because Ollama generated ~60 completion tokens at ~12.6 tokens/sec.
3. **Transport Overhead**: The client/network gap (Stage 4 wall-clock duration minus Ollama server internal duration) was consistently `< 15ms`, verifying that local HTTP transport overhead is negligible.
4. **Non-Inference Overhead**: Stages 1, 2, 3, 5, and 6 accounted for only `~118ms` combined, proving that UI and clipboard capture are not the primary bottleneck.

---

## Experimental Methodology: One-Variable-at-a-Time (OVAT)

To systematically reduce warm latency toward the <2.5s target, all future optimizations must follow strict scientific testing:

1. **Baseline Freeze**: Never change prompt wording, model, and generation flags simultaneously.
2. **Planned Experiment 1 — Output Token Capping (`num_predict`)**:
   - *Hypothesis*: Capping generation to `num_predict: 40` will reduce warm generation from ~5.0s to ~3.2s without impairing explanation quality.
   - *Test*: Compare 3 runs with unbounded tokens against 3 runs with `num_predict: 40`.
3. **Planned Experiment 2 — Model Keep-Alive Residency (`keep_alive`)**:
   - *Hypothesis*: Setting `keep_alive: "15m"` eliminates the 10.89s cold load penalty for active work sessions.
4. **Planned Experiment 3 — Token Streaming (TTFT)**:
   - *Hypothesis*: Enabling streaming (`stream: True`) delivers the first token in `< 400ms`, dramatically reducing perceived user waiting time.

---

## Acceptance Criteria
- [x] High-precision monotonic timestamps measure every pipeline boundary.
- [x] Dedicated profiler process runs decoupled over localhost UDP without blocking Kya-Ray.
- [x] Distinguishes client wall-clock duration from Ollama server internal duration.
- [x] Summarizes cold-start vs. warm cache metrics and generation speed (tokens/sec).
- [ ] Implement automated regression benchmark suite (`Planned`).
- [ ] Achieve <2.5s warm end-to-end latency via token budgeting (`Planned`).

---

## Edge Cases
- **Missing Telemetry Fields**: If an Ollama model or version omits duration fields, the profiler renders them as `unavailable` rather than treating 0 as a valid measurement.
- **Socket Dropouts**: If the profiler is not running, `prototype/main.py` ignores UDP socket send errors silently without affecting application execution.
- **Port Collisions**: If port 49999 is already bound, the profiler reports a socket binding error.

---

## Dependencies
- **Modules**: `prototype/main.py`, `prototype/pipeline_profiler.py`, `prototype/latency_test.py`.
- **Subsystems**:
  - [04-ai-response-engine.md](04-ai-response-engine.md) (supplies raw inference metrics).
  - [07-privacy-and-security.md](07-privacy-and-security.md) (audits telemetry exclusions).

---

## Open Questions
- **Open question**: Should the diagnostic profiler be maintained as a development-only tool, or should lightweight, anonymized performance counters be retained permanently for local user diagnostics?
- **Open question**: At what threshold of GPU availability should the engine adjust `num_predict` dynamically?
