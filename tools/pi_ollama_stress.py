#!/usr/bin/env python3
"""Stress-test an already-running Pi/Ollama service.

This operator tool is for the hardware prototype track only. It does not start
Ollama, call Scout APIs, write Scout state, or control hardware providers.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
import urllib.request
from statistics import mean


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manual Pi/Ollama stress probe for an already-running local model "
            "service. It prints JSONL diagnostics only."
        )
    )
    parser.add_argument("--url", default="http://127.0.0.1:11434/api/generate")
    parser.add_argument("--model", default="qwen2.5:0.5b")
    parser.add_argument("--duration-s", type=int, default=180)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--num-predict", type=int, default=160)
    parser.add_argument("--sample-s", type=float, default=5.0)
    args = parser.parse_args()
    if args.duration_s <= 0:
        parser.error("--duration-s must be positive")
    if args.workers <= 0:
        parser.error("--workers must be positive")
    if args.num_predict <= 0:
        parser.error("--num-predict must be positive")
    if args.sample_s <= 0:
        parser.error("--sample-s must be positive")
    return args


def read_temp_c() -> float:
    output = subprocess.check_output(["vcgencmd", "measure_temp"], text=True).strip()
    return float(output.split("=")[1].split("'")[0])


def read_load() -> list[str]:
    return subprocess.check_output(["cat", "/proc/loadavg"], text=True).split()[:3]


def run_stress(args: argparse.Namespace) -> None:
    prompt = (
        "你是 Scout 的離線備援模型。請根據以下狀態用繁體中文輸出一段簡短判讀："
        "使用者偏離路線 80 公尺、GPS 訊號不穩、海拔持續上升、電量 38%、無網路。"
        "請只描述風險與建議，不要宣稱已經觸發 SOS。"
    )
    stop = threading.Event()
    lock = threading.Lock()
    latencies: list[float] = []
    errors: list[str] = []
    temps: list[float] = []
    loads: list[list[str]] = []
    counts = [0 for _ in range(args.workers)]
    start = time.time()

    def monitor() -> None:
        while not stop.is_set():
            try:
                temp = read_temp_c()
                load = read_load()
                with lock:
                    temps.append(temp)
                    loads.append(load)
                print(
                    json.dumps(
                        {"t": round(time.time() - start, 1), "temp_c": temp, "load": load},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception as exc:  # pragma: no cover - Pi diagnostics only.
                with lock:
                    errors.append(f"monitor: {type(exc).__name__}: {exc}")
            stop.wait(args.sample_s)

    def worker(idx: int) -> None:
        while not stop.is_set():
            payload = {
                "model": args.model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": args.num_predict},
            }
            request = urllib.request.Request(
                args.url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(request, timeout=240) as response:
                    body = json.load(response)
                elapsed = time.perf_counter() - t0
                with lock:
                    latencies.append(elapsed)
                    counts[idx] += 1
                print(
                    json.dumps(
                        {
                            "worker": idx,
                            "latency_s": round(elapsed, 3),
                            "eval_count": body.get("eval_count"),
                            "eval_duration_ns": body.get("eval_duration"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception as exc:  # pragma: no cover - Pi diagnostics only.
                with lock:
                    errors.append(f"worker {idx}: {type(exc).__name__}: {exc}")
                time.sleep(1)

    print(
        json.dumps(
                {
                    "event": "stress_start",
                    "duration_s": args.duration_s,
                    "workers": args.workers,
                    "model": args.model,
                    "num_predict": args.num_predict,
                    "boundary": "manual_hardware_experiment_no_scout_state_writes",
                },
            ensure_ascii=False,
        ),
        flush=True,
    )
    threads = [threading.Thread(target=monitor, daemon=True)]
    threads += [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(args.workers)]
    for thread in threads:
        thread.start()
    time.sleep(args.duration_s)
    stop.set()
    for thread in threads:
        thread.join(timeout=10)

    summary = {
        "event": "stress_done",
        "duration_s": round(time.time() - start, 1),
        "workers": args.workers,
        "requests_completed": sum(counts),
        "requests_by_worker": counts,
        "latency_avg_s": round(mean(latencies), 3) if latencies else None,
        "latency_min_s": round(min(latencies), 3) if latencies else None,
        "latency_max_s": round(max(latencies), 3) if latencies else None,
        "temp_start_c": temps[0] if temps else None,
        "temp_avg_c": round(mean(temps), 2) if temps else None,
        "temp_max_c": max(temps) if temps else None,
        "load_last": loads[-1] if loads else None,
        "error_count": len(errors),
        "errors_sample": errors[:5],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    run_stress(parse_args())
