"""
prototype/latency_test.py
=========================
A standalone experimental script to benchmark the latency and token generation
speed of our local Ollama model (llama3.2:1b).

This script:
1. Sends 3 sequential requests with the same prompt to Ollama's /api/generate endpoint.
2. Uses Python's standard library (urllib.request, json, time) with zero extra dependencies.
3. Measures wall-clock time and extracts Ollama's internal timing telemetry:
   - total_duration
   - load_duration
   - prompt_eval_duration
   - eval_duration
   - eval_count
4. Calculates generation speed in tokens per second:
   Tokens/sec = eval_count / (eval_duration in seconds)
5. Computes averages across runs and highlights the cold-start vs warm-run difference.
"""

import json
import time
import urllib.error
import urllib.request

# ==============================================================================
# Benchmark Configuration
# ==============================================================================

# Ollama server endpoint and model settings
OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.2:1b"

# The standard benchmark prompt (short and consistent)
BENCHMARK_PROMPT = "Explain the word 'Ollama' in one short sentence."

# Keep-alive setting: keeps the model resident in RAM/VRAM between requests.
# Format: "10m" (10 minutes), "0" (unload immediately), or "-1" (keep loaded indefinitely).
KEEP_ALIVE = "10m"

# Number of test runs to execute
NUM_RUNS = 3

# Network request timeout in seconds
REQUEST_TIMEOUT = 60


# ==============================================================================
# Helper Functions
# ==============================================================================

def ns_to_seconds(nanoseconds):
    """Converts Ollama nanoseconds into seconds."""
    if nanoseconds is None:
        return 0.0
    return nanoseconds / 1_000_000_000.0


def send_generate_request(prompt, model=MODEL_NAME, keep_alive=KEEP_ALIVE):
    """
    Sends a non-streaming POST request to Ollama's /api/generate endpoint.

    Returns:
        tuple: (response_data: dict, wall_clock_seconds: float)
    Raises:
        ConnectionError, TimeoutError, or RuntimeError on failure.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": keep_alive,
    }

    payload_bytes = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_API_URL,
        data=payload_bytes,
        headers={"Content-Type": "application/json"},
    )

    # Measure exact wall-clock time using high-resolution performance counter
    start_time = time.perf_counter()

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw_body = response.read().decode("utf-8")
            end_time = time.perf_counter()
            wall_clock_time = end_time - start_time

            data = json.loads(raw_body)
            return data, wall_clock_time

    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"Ollama returned HTTP error {error.code}: {error.reason}."
        ) from error

    except urllib.error.URLError as error:
        raise ConnectionError(
            f"Cannot connect to Ollama at {OLLAMA_API_URL}.\n"
            "Please check that Ollama is installed and running on your computer."
        ) from error

    except TimeoutError as error:
        raise TimeoutError(
            f"Request timed out after {REQUEST_TIMEOUT} seconds waiting for Ollama."
        ) from error

    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Failed to parse JSON response from Ollama: {error}"
        ) from error


# ==============================================================================
# Main Benchmark Routine
# ==============================================================================

def run_benchmark():
    print("=" * 65)
    print("Kya-Ray: Ollama Model Latency & Speed Benchmark")
    print("=" * 65)
    print(f"Target URL:    {OLLAMA_API_URL}")
    print(f"Model:         {MODEL_NAME}")
    print(f"Keep-Alive:    {KEEP_ALIVE}")
    print(f"Prompt:        \"{BENCHMARK_PROMPT}\"")
    print(f"Runs Planned:  {NUM_RUNS}")
    print("=" * 65 + "\n")

    results = []

    for run_index in range(1, NUM_RUNS + 1):
        # Clearly distinguish the first cold-load run from subsequent warm runs
        if run_index == 1:
            run_label = f"Run {run_index} of {NUM_RUNS} (First run / Initial model load)"
        else:
            run_label = f"Run {run_index} of {NUM_RUNS} (Warm model in memory)"

        print(f"[{run_label}]")
        print("  Sending request, waiting for response...", end="", flush=True)

        try:
            data, wall_clock = send_generate_request(BENCHMARK_PROMPT)
            print(" Done! [OK]")
        except Exception as error:
            print(" FAILED!")
            print(f"\n[Error] {error}")
            return

        # Extract timing and token counts from Ollama response
        total_duration_ns = data.get("total_duration", 0)
        load_duration_ns = data.get("load_duration", 0)
        prompt_eval_ns = data.get("prompt_eval_duration", 0)
        eval_duration_ns = data.get("eval_duration", 0)
        eval_count = data.get("eval_count", 0)

        # Convert nanoseconds to seconds for readable reporting
        total_duration_sec = ns_to_seconds(total_duration_ns)
        load_duration_sec = ns_to_seconds(load_duration_ns)
        prompt_eval_sec = ns_to_seconds(prompt_eval_ns)
        eval_duration_sec = ns_to_seconds(eval_duration_ns)

        # Calculate generation speed (tokens per second)
        # Formula: eval_count / eval_duration_in_seconds
        if eval_duration_sec > 0:
            tokens_per_sec = eval_count / eval_duration_sec
        else:
            tokens_per_sec = 0.0

        # Store run data for summary statistics
        results.append({
            "run": run_index,
            "wall_clock": wall_clock,
            "total_duration": total_duration_sec,
            "load_duration": load_duration_sec,
            "prompt_eval_duration": prompt_eval_sec,
            "eval_duration": eval_duration_sec,
            "eval_count": eval_count,
            "tokens_per_sec": tokens_per_sec,
        })

        # Print detailed metrics for this run
        print(f"  - Wall-clock time:       {wall_clock:.3f} s")
        print(f"  - Ollama total_duration: {total_duration_sec:.3f} s  ({total_duration_ns:,} ns)")
        print(f"  - load_duration:         {load_duration_sec:.3f} s  ({load_duration_ns:,} ns)")
        print(f"  - prompt_eval_duration:  {prompt_eval_sec:.3f} s  ({prompt_eval_ns:,} ns)")
        print(f"  - eval_duration:         {eval_duration_sec:.3f} s  ({eval_duration_ns:,} ns)")
        print(f"  - eval_count:            {eval_count} tokens")
        print(f"  - Generation speed:      {tokens_per_sec:.2f} tokens/second")
        print()

    # ==========================================================================
    # Summary & Averages
    # ==========================================================================
    if not results:
        return

    wall_times = [r["wall_clock"] for r in results]
    gen_speeds = [r["tokens_per_sec"] for r in results]

    avg_wall_all = sum(wall_times) / len(wall_times)
    avg_speed_all = sum(gen_speeds) / len(gen_speeds)

    print("=" * 65)
    print("Benchmark Summary & Averages")
    print("=" * 65)
    print(f"Total Completed Runs:        {len(results)}")
    print(f"Average Wall-Clock Time:     {avg_wall_all:.3f} s")
    print(f"Average Generation Speed:    {avg_speed_all:.2f} tokens/second")

    # If we ran more than 1 run, also display the warm runs average (excluding run 1)
    if len(results) > 1:
        warm_wall = wall_times[1:]
        warm_speeds = gen_speeds[1:]
        avg_warm_wall = sum(warm_wall) / len(warm_wall)
        avg_warm_speed = sum(warm_speeds) / len(warm_speeds)

        print("-" * 65)
        print("Warm Runs Average (Runs 2 to 3, excluding cold load):")
        print(f"  - Warm Wall-Clock Time:    {avg_warm_wall:.3f} s")
        print(f"  - Warm Generation Speed:   {avg_warm_speed:.2f} tokens/second")

    print("=" * 65)


if __name__ == "__main__":
    run_benchmark()
