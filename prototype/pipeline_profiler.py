"""
prototype/pipeline_profiler.py
==============================
A standalone end-to-end pipeline latency profiler for Kya-Ray V7.

Architecture:
- Runs as a separate process listening on a local-only UDP socket (127.0.0.1:49999).
- Receives structured diagnostic telemetry from Kya-Ray containing ONLY:
    run_id (int), event (str), ts (monotonic float), error (str or null)
- ZERO user text or AI content is transmitted or logged.
- Measures each pipeline boundary using high-resolution monotonic timestamps (time.perf_counter()).
- Computes exact stage durations, unaccounted gaps, total end-to-end latency,
  and multi-run averages across 3 runs.
"""

import argparse
import json
import socket
import sys
import time

# ==============================================================================
# Configuration
# ==============================================================================

PROFILER_HOST = "127.0.0.1"
PROFILER_PORT = 49999
BUFFER_SIZE = 4096
DEFAULT_RUNS = 3
RUN_TIMEOUT_SECONDS = 30.0  # Max wait time for a single run to complete

# Ordered list of expected pipeline milestone events
ORDERED_EVENTS = [
    "hotkey_detected",
    "activation_started",
    "text_capture_started",
    "text_capture_completed",
    "ollama_request_started",
    "ollama_response_received",
    "ui_update_queued",
    "answer_displayed",
]

STAGE_NAMES = [
    ("Stage 1: Worker Thread Startup", "hotkey_detected", "activation_started"),
    ("Stage 2: Clipboard Text Capture", "text_capture_started", "text_capture_completed"),
    ("Stage 3: Pre-Request Setup", "text_capture_completed", "ollama_request_started"),
    ("Stage 4: Ollama Local Inference", "ollama_request_started", "ollama_response_received"),
    ("Stage 5: UI Queue Push", "ollama_response_received", "ui_update_queued"),
    ("Stage 6: UI Queue Poll & Render", "ui_update_queued", "answer_displayed"),
]


# ==============================================================================
# Telemetry Analysis & Reporting
# ==============================================================================

def parse_ollama_metrics(raw_metrics):
    """
    Parses and converts Ollama internal metrics dictionary.
    Converts nanosecond duration fields to milliseconds.
    Validates token counts and calculates generation speed (tokens/sec).
    Missing, invalid, or non-numeric fields remain None (displayed as 'unavailable').
    """
    if not isinstance(raw_metrics, dict):
        return None

    parsed = {}
    duration_fields = [
        "total_duration",
        "load_duration",
        "prompt_eval_duration",
        "eval_duration",
    ]
    for field in duration_fields:
        val = raw_metrics.get(field)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
            parsed[f"{field}_ms"] = val / 1_000_000.0
        else:
            parsed[f"{field}_ms"] = None

    for count_field in ["prompt_eval_count", "eval_count"]:
        val = raw_metrics.get(count_field)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
            parsed[count_field] = val
        elif isinstance(val, float) and val.is_integer() and val >= 0:
            parsed[count_field] = int(val)
        else:
            parsed[count_field] = None

    eval_count = parsed.get("eval_count")
    eval_dur_ms = parsed.get("eval_duration_ms")
    if eval_count is not None and eval_dur_ms is not None and eval_dur_ms > 0:
        parsed["tokens_per_sec"] = eval_count / (eval_dur_ms / 1000.0)
    else:
        parsed["tokens_per_sec"] = None

    return parsed


def analyze_run(run_data):
    """
    Computes stage durations, total latency, and gap times for a completed run.

    Returns:
        dict containing metrics, or None if essential events are missing.
    """
    events = run_data["events"]
    aborted = run_data.get("aborted")

    if aborted:
        return {
            "success": False,
            "error": aborted.get("error", "pipeline_aborted"),
            "events": events,
            "ollama_metrics": None,
        }

    # Verify all expected milestone events are present
    missing = [e for e in ORDERED_EVENTS if e not in events]
    if missing:
        return {
            "success": False,
            "error": f"Missing expected events: {', '.join(missing)}",
            "events": events,
            "ollama_metrics": None,
        }

    t0 = events["hotkey_detected"]
    total_ms = (events["answer_displayed"] - t0) * 1000.0

    stages = []
    accounted_ms = 0.0

    for stage_label, start_ev, end_ev in STAGE_NAMES:
        duration_ms = (events[end_ev] - events[start_ev]) * 1000.0
        start_offset_ms = (events[start_ev] - t0) * 1000.0
        end_offset_ms = (events[end_ev] - t0) * 1000.0
        pct = (duration_ms / total_ms * 100.0) if total_ms > 0 else 0.0

        stages.append({
            "name": stage_label,
            "duration_ms": duration_ms,
            "start_offset_ms": start_offset_ms,
            "end_offset_ms": end_offset_ms,
            "pct": pct,
        })
        accounted_ms += duration_ms

    # Unaccounted / gap time (e.g. between activation_started and text_capture_started)
    gap_ms = max(0.0, total_ms - accounted_ms)
    ollama_metrics = parse_ollama_metrics(run_data.get("metrics"))

    return {
        "success": True,
        "total_ms": total_ms,
        "accounted_ms": accounted_ms,
        "gap_ms": gap_ms,
        "stages": stages,
        "events": events,
        "ollama_metrics": ollama_metrics,
    }


def print_run_report(run_id, analysis, target_runs):
    """Prints a clear, formatted breakdown for a single run."""
    print("\n" + "-" * 72)
    print(f"  RUN {run_id} of {target_runs} PIPELINE BREAKDOWN")
    print("-" * 72)

    if not analysis["success"]:
        print(f"  [STATUS] INCOMPLETE / ABORTED: {analysis['error']}")
        print(f"  [EVENTS RECORDED]: {list(analysis['events'].keys())}")
        print("-" * 72)
        return

    total_ms = analysis["total_ms"]
    print(f"  {'Stage Name':<34} | {'Offset':>9} | {'Duration':>10} | {'Share':>6}")
    print("  " + "-" * 68)

    for s in analysis["stages"]:
        print(
            f"  {s['name']:<34} | "
            f"+{s['start_offset_ms']:>7.2f}ms | "
            f"{s['duration_ms']:>8.2f}ms | "
            f"{s['pct']:>5.1f}%"
        )
        if "Stage 4:" in s["name"]:
            m = analysis.get("ollama_metrics")
            if m is not None:
                print("  " + " " * 4 + "|-- Ollama Server Internal Breakdown:")

                # load_duration
                if m["load_duration_ms"] is not None:
                    load_str = f"{m['load_duration_ms']:>8.2f}ms"
                    extra = " (Model loaded into memory)" if m["load_duration_ms"] > 500 else " (Warm cache in memory)"
                else:
                    load_str = "unavailable"
                    extra = ""
                print(f"  {'    |   - load_duration:':<34} |           | {load_str:>10} |{extra}")

                # prompt_eval_duration
                if m["prompt_eval_duration_ms"] is not None:
                    p_dur_str = f"{m['prompt_eval_duration_ms']:>8.2f}ms"
                    p_cnt = f" ({m['prompt_eval_count']} tokens)" if m["prompt_eval_count"] is not None else ""
                else:
                    p_dur_str = "unavailable"
                    p_cnt = ""
                print(f"  {'    |   - prompt_eval_duration:':<34} |           | {p_dur_str:>10} |{p_cnt}")

                # eval_duration
                if m["eval_duration_ms"] is not None:
                    e_dur_str = f"{m['eval_duration_ms']:>8.2f}ms"
                    tok_str = f"{m['eval_count']} tokens" if m["eval_count"] is not None else "unavailable tokens"
                    speed_str = f" @ {m['tokens_per_sec']:.2f} tok/s" if m["tokens_per_sec"] is not None else ""
                    e_cnt = f" ({tok_str}{speed_str})"
                else:
                    e_dur_str = "unavailable"
                    e_cnt = ""
                print(f"  {'    |   - eval_duration:':<34} |           | {e_dur_str:>10} |{e_cnt}")

                # total_duration vs wall-clock
                if m["total_duration_ms"] is not None:
                    tot_str = f"{m['total_duration_ms']:>8.2f}ms"
                    gap = s["duration_ms"] - m["total_duration_ms"]
                    gap_str = f" (Client/network gap: {gap:.2f}ms)" if gap >= 0 else ""
                else:
                    tot_str = "unavailable"
                    gap_str = ""
                print(f"  {'    |   - total_duration (server):':<34} |           | {tot_str:>10} |{gap_str}")
            else:
                print("  " + " " * 4 + "|-- Ollama Server Internal Breakdown: unavailable")

    print("  " + "-" * 68)
    if analysis["gap_ms"] > 0.01:
        gap_pct = (analysis["gap_ms"] / total_ms) * 100.0
        print(f"  {'Unaccounted / Inter-Stage Gaps':<34} |           | {analysis['gap_ms']:>8.2f}ms | {gap_pct:>5.1f}%")

    print(f"  {'TOTAL END-TO-END LATENCY':<34} |           | {total_ms:>8.2f}ms | 100.0%")
    print("-" * 72)


def print_final_summary(successful_runs):
    """Prints aggregate statistics and comparisons across all completed runs."""
    count = len(successful_runs)
    if count == 0:
        print("\n[Summary] No runs completed successfully.")
        return

    print("\n" + "=" * 72)
    print(f"  KYA-RAY V7 PIPELINE BENCHMARK SUMMARY ({count} RUNS)")
    print("=" * 72)

    # Header for comparison table
    run_headers = " | ".join([f"Run {r['run_id']:<2}" for r in successful_runs])
    print(f"  {'Stage / Metric':<34} | {run_headers} | {'Average':>9}")
    print("  " + "-" * 68)

    # Average for each stage
    for idx, (stage_label, _, _) in enumerate(STAGE_NAMES):
        durations = [r["analysis"]["stages"][idx]["duration_ms"] for r in successful_runs]
        avg_d = sum(durations) / count
        vals = " | ".join([f"{d:>6.1f}ms" for d in durations])
        print(f"  {stage_label:<34} | {vals} | {avg_d:>7.1f}ms")

    # Unaccounted gap average
    gaps = [r["analysis"]["gap_ms"] for r in successful_runs]
    avg_gap = sum(gaps) / count
    gap_vals = " | ".join([f"{g:>6.1f}ms" for g in gaps])
    print(f"  {'Unaccounted Gaps':<34} | {gap_vals} | {avg_gap:>7.1f}ms")

    print("  " + "-" * 68)

    # Total latency
    totals = [r["analysis"]["total_ms"] for r in successful_runs]
    avg_total = sum(totals) / count
    total_vals = " | ".join([f"{t:>6.1f}ms" for t in totals])
    print(f"  {'TOTAL PIPELINE LATENCY':<34} | {total_vals} | {avg_total:>7.1f}ms")

    # Ollama internal metrics summary if available on any run
    has_any_ollama = any(r["analysis"].get("ollama_metrics") is not None for r in successful_runs)
    if has_any_ollama:
        print("  " + "-" * 68)
        print("  Ollama Server-Side Timing Telemetry (Internal):")

        ollama_fields = [
            ("  - load_duration", "load_duration_ms", "ms"),
            ("  - prompt_eval_duration", "prompt_eval_duration_ms", "ms"),
            ("  - eval_duration", "eval_duration_ms", "ms"),
            ("  - total_duration (server)", "total_duration_ms", "ms"),
            ("  - eval_count (tokens)", "eval_count", "tokens"),
            ("  - Generation Speed", "tokens_per_sec", "speed"),
        ]

        for label, key, unit in ollama_fields:
            vals = []
            numeric_vals = []
            for r in successful_runs:
                m = r["analysis"].get("ollama_metrics")
                val = m.get(key) if m else None
                if val is not None:
                    numeric_vals.append(val)
                    if unit == "ms":
                        vals.append(f"{val:>6.1f}ms")
                    elif unit == "tokens":
                        vals.append(f"{val:>6d}  ")
                    else:  # speed
                        vals.append(f"{val:>5.1f}t/s ")
                else:
                    vals.append(f"{'unavailable':>8}")

            row_vals = " | ".join(vals)
            if numeric_vals:
                avg_val = sum(numeric_vals) / len(numeric_vals)
                if unit == "ms":
                    avg_str = f"{avg_val:>7.1f}ms"
                elif unit == "tokens":
                    avg_str = f"{avg_val:>8.1f}"
                else:
                    avg_str = f"{avg_val:>7.1f}t/s"
            else:
                avg_str = f"{'unavailable':>9}"
            print(f"  {label:<34} | {row_vals} | {avg_str}")

    print("=" * 72)

    # Highlight warm runs if more than 1 run completed
    if count >= 2:
        warm_totals = totals[1:]
        avg_warm = sum(warm_totals) / len(warm_totals)
        cold_total = totals[0]
        print(f"  * Cold Run 1 Total Latency: {cold_total:.1f} ms  ({cold_total / 1000.0:.2f} s)")
        print(f"  * Warm Average Total (2+):  {avg_warm:.1f} ms  ({avg_warm / 1000.0:.2f} s)")
        if count >= 3:
            # Check warm generation speed
            warm_speeds = []
            for r in successful_runs[1:]:
                m = r["analysis"].get("ollama_metrics")
                if m and m.get("tokens_per_sec") is not None:
                    warm_speeds.append(m["tokens_per_sec"])
            if warm_speeds:
                avg_warm_speed = sum(warm_speeds) / len(warm_speeds)
                print(f"  * Warm Generation Speed:    {avg_warm_speed:.2f} tokens/second")
        print("=" * 72 + "\n")


# ==============================================================================
# Main Profiler Server Loop
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Kya-Ray V7 Full-Pipeline Latency Profiler")
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help=f"Number of benchmark runs to collect (default: {DEFAULT_RUNS})",
    )
    args = parser.parse_args()
    target_runs = args.runs

    print("=" * 72)
    print("  Kya-Ray V7: Full-Pipeline Latency Profiler")
    print("=" * 72)
    print(f"  Listening on:     udp://{PROFILER_HOST}:{PROFILER_PORT}")
    print(f"  Target Runs:      {target_runs}")
    print(f"  Telemetry Scope:  Run IDs, Event Names, Monotonic Timestamps (No Text)")
    print("=" * 72)
    print("\n[Status] Waiting for Kya-Ray hotkey activations (Ctrl + Shift + J)...")
    print("         (Press Ctrl + C here at any time to finish and view summary)\n")

    # Bind UDP diagnostic receiver
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((PROFILER_HOST, PROFILER_PORT))
    sock.settimeout(0.5)

    runs = {}  # run_id -> {"events": {name: ts}, "aborted": None, "start_time": float}
    successful_runs = []
    completed_run_ids = set()

    try:
        while len(successful_runs) < target_runs:
            try:
                raw_data, _ = sock.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                # Check for in-flight runs that have timed out
                now = time.perf_counter()
                for rid, rinfo in list(runs.items()):
                    if rid not in completed_run_ids:
                        if now - rinfo["start_time"] > RUN_TIMEOUT_SECONDS:
                            completed_run_ids.add(rid)
                            analysis = {
                                "success": False,
                                "error": f"Timed out after {RUN_TIMEOUT_SECONDS}s",
                                "events": rinfo["events"],
                            }
                            print_run_report(rid, analysis, target_runs)
                continue

            # Parse incoming event packet
            try:
                packet = json.loads(raw_data.decode("utf-8"))
            except Exception:
                continue

            run_id = packet.get("run_id")
            event = packet.get("event")
            ts = packet.get("ts")
            error = packet.get("error")
            metrics = packet.get("metrics")

            if run_id is None or event is None or ts is None:
                continue

            # Initialize new run container
            if run_id not in runs:
                runs[run_id] = {
                    "events": {},
                    "aborted": None,
                    "start_time": ts,
                    "metrics": None,
                }
                print(f"[*] Run {run_id} triggered (hotkey detected)...", flush=True)

            run_entry = runs[run_id]

            # Save numeric telemetry metrics if provided
            if metrics and isinstance(metrics, dict):
                run_entry["metrics"] = metrics

            # Handle abort events (e.g. no_selection, ollama_failed)
            if event == "pipeline_aborted":
                run_entry["aborted"] = {"error": error or "aborted"}
                completed_run_ids.add(run_id)
                analysis = analyze_run(run_entry)
                print_run_report(run_id, analysis, target_runs)
                continue

            run_entry["events"][event] = ts

            # Check if this run has completed all pipeline stages
            if event == "answer_displayed" and run_id not in completed_run_ids:
                completed_run_ids.add(run_id)
                analysis = analyze_run(run_entry)
                print_run_report(run_id, analysis, target_runs)

                if analysis["success"]:
                    successful_runs.append({"run_id": run_id, "analysis": analysis})
                    remaining = target_runs - len(successful_runs)
                    if remaining > 0:
                        print(f"[Status] {remaining} run(s) remaining. Highlight text and press Ctrl + Shift + J.")

    except KeyboardInterrupt:
        print("\n\n[Notice] Profiler interrupted by user. Generating summary of completed runs...")

    finally:
        sock.close()
        print_final_summary(successful_runs)


if __name__ == "__main__":
    main()
