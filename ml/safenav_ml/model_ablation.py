"""Phase 8 model ablation (PLAN.md section 11): production configuration on the full 500
benchmark with three models, reporting top-1, top-3, out-of-graph rate, p50/p90 latency and
llama-server RSS. Reuses ml/safenav_ml/run_phase5_benchmark.py's resolver and metrics rather
than a second implementation; this script only orchestrates llama-server restarts across models
and collects the per-model summary table.

Each model is loaded into a fresh llama-server one at a time (one GGUF fits comfortably, three
do not need to be resident together), so this script starts/stops the host Metal server itself.
It expects `third_party/llama.cpp/build/bin/llama-server` to already be built (docs/hardware/
llama-server.md) and the three GGUFs to already be present under `models/`.

Usage (host, conda env tf_env):
    python3 ml/safenav_ml/model_ablation.py --out-dir data/runs/model_ablation \
        --report docs/results/model_ablation.json
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from safenav_ml import metrics  # noqa: E402
import run_phase5_benchmark as bench  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LLAMA_SERVER_BIN = os.path.join(REPO_ROOT, "third_party", "llama.cpp", "build", "bin", "llama-server")
PORT = 8099

MODELS = {
    "phi3-mini-4k-instruct.Q4_K_M": "phi3-mini-4k-instruct.Q4_K_M.gguf",
    "tinyllama-1.1b-chat-v1.0.Q4_K_M": "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
    "phi3.5-mini-instruct.Q4_K_M": "phi3.5-mini-instruct.Q4_K_M.gguf",
}


def wait_health(port: int, timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def start_server(model_path: str, port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [LLAMA_SERVER_BIN, "--model", model_path, "--port", str(port), "--ctx-size", "2048", "-ngl", "99"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not wait_health(port):
        proc.terminate()
        raise RuntimeError(f"llama-server for {model_path} did not become healthy within timeout")
    return proc


def stop_server(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def measure_rss_mb(proc: subprocess.Popen) -> Optional[float]:
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(proc.pid)], capture_output=True, text=True)
        rss_kb = float(out.stdout.strip())
        return rss_kb / 1024.0
    except Exception:
        return None


def run_one_model(name: str, gguf: str, out_dir: str) -> Dict:
    model_path = os.path.join(REPO_ROOT, "models", gguf)
    if not os.path.exists(model_path):
        return {"model": name, "error": f"missing {model_path}"}

    proc = start_server(model_path, PORT)
    time.sleep(1.0)
    rss_mb = measure_rss_mb(proc)
    try:
        graph = bench.AnnotationGraph.from_file(bench.ANNOTATIONS_PATH)
        core = bench.ResolverCore(
            model_path=model_path,
            graph=graph,
            fewshot_count=bench.PRODUCTION["fewshot_count"],
            temperature=bench.PRODUCTION["temperature"],
            backend="http",
            backend_url=f"http://127.0.0.1:{PORT}",
        )
        rows = bench.select_rows("full")
        records = bench.run(core, rows, name, grammar_on=True)
    finally:
        stop_server(proc)

    out_path = os.path.join(out_dir, f"{name}.jsonl")
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")

    lat = metrics.latency_percentiles(records, exclude_cold=True)
    return {
        "model": name,
        "n": len(records),
        "top1": metrics.top1(records),
        "top3": metrics.top3(records),
        "oog_rate": metrics.oog_rate(records),
        "p50_ms": lat["p50_ms"],
        "p90_ms": lat["p90_ms"],
        "rss_mb": rss_mb,
        "out_path": out_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "data", "runs", "model_ablation"))
    parser.add_argument("--report", default=os.path.join(REPO_ROOT, "docs", "results", "model_ablation.json"))
    parser.add_argument("--only", action="append", choices=list(MODELS), default=None)
    args = parser.parse_args()

    selected = args.only or list(MODELS)
    results: List[Dict] = []
    for name in selected:
        print(f"=== {name} ===", file=sys.stderr)
        result = run_one_model(name, MODELS[name], args.out_dir)
        print(json.dumps(result), file=sys.stderr)
        results.append(result)

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
