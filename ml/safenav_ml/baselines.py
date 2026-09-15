"""Baseline comparisons B0-B2, B2b, B4, B4b (docs/phase-4-brief.md section 5). B0-B2 are
seconds on the host, no model, no API. B2b/B4/B4b call the Mistral API.

    python ml/safenav_ml/baselines.py --pairs data/benchmark/synthetic_500.jsonl \
        --out data/runs/baselines
    python ml/safenav_ml/baselines.py --embed --pairs data/benchmark/synthetic_500.jsonl \
        --out data/runs/baselines
    python ml/safenav_ml/baselines.py --cloud --model ministral-14b-latest --tag b4 \
        --pairs data/benchmark/synthetic_500.jsonl --out data/runs/baselines
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROS2_PY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ros2_ws", "src", "semantic_waypoint_planner",
)
sys.path.insert(0, ROS2_PY_PATH)

from rapidfuzz import fuzz, process  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.metrics.pairwise import cosine_similarity  # noqa: E402

from safenav_ml.mistral_client import chat, unwrap_one_level, _api_key  # noqa: E402
from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.resolver_core import fast_path_match, normalize_command  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANNOTATIONS_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "maps", "room_annotations.json"
)

# Thresholds tuned on data/benchmark/subsample_64.jsonl by a top1 sweep (see
# docs/reports/phase-4-prompt-study.md for the swept values and scores).
B1_FUZZY_THRESHOLD = 40.0
B2_COSINE_THRESHOLD = 0.20
B2B_COSINE_THRESHOLD = 0.55


def _load_pairs(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    for i, r in enumerate(rows):
        r.setdefault("id", f"p{i:04d}")
    return rows


def _room_document(graph: AnnotationGraph, name: str) -> str:
    room = graph.get_room(name)
    parts = [name.replace("_", " ")] + list(room.aliases) + list(room.tags)
    parts.append(graph.adjacency_text(name))
    return " ".join(parts)


def run_b0(pairs: List[dict], graph: AnnotationGraph) -> List[dict]:
    rows = []
    for p in pairs:
        t0 = time.monotonic()
        match = fast_path_match(graph, p["command"])
        latency_ms = (time.monotonic() - t0) * 1000.0
        predicted = match or "none"
        rows.append({
            "id": p["id"], "command": p["command"], "expected": p["expected"], "category": p["category"],
            "predicted": predicted, "top_k_rooms": [predicted], "out_of_graph": False,
            "mode": "b0_exact", "latency_ms": latency_ms,
        })
    return rows


def run_b1(pairs: List[dict], graph: AnnotationGraph, threshold: float = B1_FUZZY_THRESHOLD) -> List[dict]:
    choices: Dict[str, str] = {}  # phrase -> canonical name
    for room in graph.rooms:
        choices[room.name.replace("_", " ")] = room.name
        for alias in room.aliases:
            choices[alias] = room.name

    rows = []
    for p in pairs:
        t0 = time.monotonic()
        norm = normalize_command(p["command"])
        matches = process.extract(norm, list(choices.keys()), scorer=fuzz.token_set_ratio, limit=10)
        ranking: List[Tuple[str, float]] = []
        seen = set()
        for phrase, score, _ in matches:
            name = choices[phrase]
            if name in seen:
                continue
            seen.add(name)
            ranking.append((name, score / 100.0))
        ranking.sort(key=lambda kv: kv[1], reverse=True)
        latency_ms = (time.monotonic() - t0) * 1000.0
        top_score = ranking[0][1] * 100.0 if ranking else 0.0
        predicted = ranking[0][0] if ranking and top_score >= threshold else "none"
        rows.append({
            "id": p["id"], "command": p["command"], "expected": p["expected"], "category": p["category"],
            "predicted": predicted, "top_k_rooms": [n for n, _ in ranking[:5]], "out_of_graph": False,
            "mode": "b1_fuzzy", "latency_ms": latency_ms,
        })
    return rows


def run_b2(pairs: List[dict], graph: AnnotationGraph, threshold: float = B2_COSINE_THRESHOLD) -> List[dict]:
    names = graph.canonical_names
    docs = [_room_document(graph, n) for n in names]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
    doc_matrix = vectorizer.fit_transform(docs)

    rows = []
    for p in pairs:
        t0 = time.monotonic()
        query_vec = vectorizer.transform([normalize_command(p["command"])])
        sims = cosine_similarity(query_vec, doc_matrix)[0]
        ranking = sorted(zip(names, sims.tolist()), key=lambda kv: kv[1], reverse=True)
        latency_ms = (time.monotonic() - t0) * 1000.0
        predicted = ranking[0][0] if ranking and ranking[0][1] >= threshold else "none"
        rows.append({
            "id": p["id"], "command": p["command"], "expected": p["expected"], "category": p["category"],
            "predicted": predicted, "top_k_rooms": [n for n, _ in ranking[:5]], "out_of_graph": False,
            "mode": "b2_tfidf", "latency_ms": latency_ms,
        })
    return rows


def _mistral_embed(texts: List[str], model: str = "mistral-embed", batch_size: int = 50) -> List[List[float]]:
    import requests

    headers = {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}
    out: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = requests.post(
            "https://api.mistral.ai/v1/embeddings",
            headers=headers, json={"model": model, "input": batch}, timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        out.extend([d["embedding"] for d in data["data"]])
    return out


def run_b2b(pairs: List[dict], graph: AnnotationGraph, threshold: float = B2B_COSINE_THRESHOLD) -> List[dict]:
    import numpy as np

    names = graph.canonical_names
    docs = [_room_document(graph, n) for n in names]
    doc_embeddings = np.array(_mistral_embed(docs))

    rows = []
    commands = [p["command"] for p in pairs]
    cmd_embeddings = np.array(_mistral_embed(commands))
    for p, cmd_emb in zip(pairs, cmd_embeddings):
        t0 = time.monotonic()
        sims = cosine_similarity([cmd_emb], doc_embeddings)[0]
        ranking = sorted(zip(names, sims.tolist()), key=lambda kv: kv[1], reverse=True)
        latency_ms = (time.monotonic() - t0) * 1000.0
        predicted = ranking[0][0] if ranking and ranking[0][1] >= threshold else "none"
        rows.append({
            "id": p["id"], "command": p["command"], "expected": p["expected"], "category": p["category"],
            "predicted": predicted, "top_k_rooms": [n for n, _ in ranking[:5]], "out_of_graph": False,
            "mode": "b2b_embed", "latency_ms": latency_ms,
        })
    return rows


CLOUD_SYSTEM_TEMPLATE = """You are the semantic waypoint resolver for the {facility} facility \
robot. A human operator gives a natural language navigation command. Choose exactly one \
location from the closed list below that the operator most likely means, or "none" if no \
location plausibly matches.

Known locations (canonical name: aliases):
{locations_block}

Spatial relationships:
{adjacency_block}

Respond with a single JSON object: {{"room": "<canonical_name_or_none>", "confidence": <0.00-0.99>}}. \
Use only a canonical name from the list above, exactly as written, or "none". Do not explain \
your answer."""


def _cloud_system_text(graph: AnnotationGraph) -> str:
    lines = []
    for room in graph.rooms:
        aliases = ", ".join(room.aliases) if room.aliases else "(no aliases)"
        lines.append(f"- {room.name}: {aliases}")
    sentences = []
    for room in graph.rooms:
        text = graph.adjacency_text(room.name)
        if text and not text.endswith("no recorded adjacency."):
            sentences.append(text)
    return CLOUD_SYSTEM_TEMPLATE.format(
        facility=graph.facility or "safenav_lab",
        locations_block="\n".join(lines),
        adjacency_block="\n".join(sentences) if sentences else "No spatial relationships recorded.",
    )


def _cloud_one(system_text: str, command: str, model: str, canonical_names: List[str]) -> dict:
    t0 = time.monotonic()
    try:
        result = chat(
            [{"role": "system", "content": system_text}, {"role": "user", "content": command}],
            model=model, temperature=0.0,
        )
        data = unwrap_one_level(result["data"], ["room"])
        room = data.get("room")
        malformed = "room" not in data
    except Exception:
        room, malformed = None, True
    latency_ms = (time.monotonic() - t0) * 1000.0
    out_of_graph = room is not None and room != "none" and room not in canonical_names
    return {
        "predicted": room or "none", "malformed": malformed, "out_of_graph": out_of_graph,
        "latency_ms": latency_ms, "top_k_rooms": [room] if room else [],
    }


def run_cloud(pairs: List[dict], graph: AnnotationGraph, model: str, concurrency: int = 4) -> List[dict]:
    system_text = _cloud_system_text(graph)
    canonical_names = graph.canonical_names
    rows: List[Optional[dict]] = [None] * len(pairs)

    def work(i: int, p: dict) -> Tuple[int, dict]:
        out = _cloud_one(system_text, p["command"], model, canonical_names)
        row = {
            "id": p["id"], "command": p["command"], "expected": p["expected"], "category": p["category"],
            "mode": f"cloud_{model}",
        }
        row.update(out)
        return i, row

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(work, i, p) for i, p in enumerate(pairs)]
        for fut in concurrent.futures.as_completed(futures):
            i, row = fut.result()
            rows[i] = row
            if i % 50 == 0:
                print(f"  cloud[{model}]: {i}/{len(pairs)}")
    return rows  # type: ignore[return-value]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500.jsonl"))
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "data", "runs", "baselines"))
    ap.add_argument("--embed", action="store_true")
    ap.add_argument("--cloud", action="store_true")
    ap.add_argument("--model", default="ministral-14b-latest")
    ap.add_argument("--tag", default="b4")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    pairs = _load_pairs(args.pairs)

    def write(name: str, rows: List[dict]) -> None:
        path = os.path.join(args.out, f"{name}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        print(f"wrote {path} ({len(rows)} rows)")

    if args.cloud:
        rows = run_cloud(pairs, graph, args.model, args.concurrency)
        write(args.tag, rows)
        return
    if args.embed:
        write("b2b", run_b2b(pairs, graph))
        return

    write("b0", run_b0(pairs, graph))
    write("b1", run_b1(pairs, graph))
    write("b2", run_b2(pairs, graph))


if __name__ == "__main__":
    main()
