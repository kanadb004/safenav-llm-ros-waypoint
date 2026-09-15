"""Generate the synthetic benchmark (PLAN.md Phase 4, docs/phase-4-brief.md section 4) with
``ministral-14b-latest`` over the Mistral REST API. No SDK, temperature 1.0, batches of 25
pairs per request, 20 percent surplus per category so dedupe/review/checker can reject freely.

Usage:
    python ml/safenav_ml/gen_dataset.py --dry-run
    python ml/safenav_ml/gen_dataset.py --out data/runs/gen_dataset
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rapidfuzz import fuzz  # noqa: E402
from safenav_ml.mistral_client import chat, unwrap_one_level  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANNOTATIONS_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "maps", "room_annotations.json"
)
FEWSHOT_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "config", "prompts", "fewshot.jsonl"
)

RESOLVABLE_CATEGORIES = [
    "direct", "alias", "spatial", "functional", "negation", "abbreviation", "multi_hop",
]
TARGET_PER_RESOLVABLE = 65
TARGET_ADVERSARIAL_500 = 45
BATCH_SIZE = 25
RESOLVABLE_BATCHES = 4   # 100 candidates per category, target 65 after dedupe
ADVERSARIAL_BATCHES = 5  # 125 candidates, target 45 (for 500) + 45 (for adversarial_50)

CATEGORY_PROMPTS = {
    "direct": "Direct naming: the command names a location by its exact canonical name or a "
              "close paraphrase of it (e.g. 'go to the kitchen').",
    "alias": "Alias use: the command uses one of the location's listed aliases instead of its "
             "canonical name (e.g. 'take me to the break room' for kitchen).",
    "spatial": "Spatial reference: the command describes the location relative to another "
               "location using the edges/adjacency relations given below (e.g. 'the room next "
               "to the server room').",
    "functional": "Functional description: the command describes what the location is used for "
                  "or contains, without naming it (e.g. 'somewhere I can charge the robot').",
    "negation": "Negation: the command rules out one or more locations and implies another "
                "(e.g. 'not the kitchen, the other break area' or 'anywhere but the office' when "
                "only one plausible target remains).",
    "abbreviation": "Abbreviation: the command uses a shortened, informal, or abbreviated form "
                     "of a name or alias (e.g. 'srv room' for server_room, 'chg dock' for "
                     "charging_dock).",
    "multi_hop": "Multi-hop reference: the command requires combining two pieces of information "
                 "(an object plus a location, or two relations) to identify a single location, "
                 "e.g. 'the desk next to the printer' or 'the bench in the lab near the door'.",
    "adversarial": "Adversarial / unresolvable: the command sounds like a navigation request but "
                   "does not plausibly match any location in the list (mentions a real-world "
                   "place not on the list, is vague to the point of being unanswerable, or names "
                   "a location type the facility does not have). The expected answer is always "
                   "the literal string \"none\".",
}

SYSTEM_INSTRUCTIONS = """You are generating a benchmark dataset for a semantic waypoint \
resolver robot at a facility called "safenav_lab". The robot understands exactly the closed \
list of locations given below (canonical names, aliases, tags, and spatial edges) and nothing \
else. For the requested category, generate natural-language navigation commands a human \
operator might realistically give the robot, each paired with the single canonical location \
name the command should resolve to (or the literal string "none" for the adversarial \
category). Vary phrasing, sentence length, and politeness. Do not reuse any command from the \
"do not reuse" list. Respond as a JSON object: {"pairs": [{"command": str, "expected": str, \
"category": str, "rationale": str}, ...]} with exactly the requested number of pairs. \
"rationale" is one short sentence on why "expected" follows from the command."""


def render_graph_block(graph: dict) -> str:
    lines = []
    for room in graph["rooms"]:
        aliases = ", ".join(room.get("aliases", []))
        tags = ", ".join(room.get("tags", []))
        lines.append(f"- {room['name']} (aliases: {aliases}; tags: {tags})")
    edge_lines = [
        f"- {e['from']} {e['relation'].replace('_', ' ')} {e['to']}" for e in graph.get("edges", [])
    ]
    return "Locations:\n" + "\n".join(lines) + "\n\nEdges:\n" + "\n".join(edge_lines)


def load_fewshot_commands() -> List[str]:
    commands = []
    with open(FEWSHOT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            commands.append(json.loads(line)["command"])
    return commands


def build_messages(category: str, graph: dict, n: int, do_not_reuse: List[str]) -> List[Dict[str, str]]:
    user = (
        f"{render_graph_block(graph)}\n\n"
        f"Category: {category}\n{CATEGORY_PROMPTS[category]}\n\n"
        f"Generate exactly {n} pairs for this category.\n\n"
        "Do not reuse any of these commands (already used elsewhere):\n"
        + "\n".join(f"- {c}" for c in do_not_reuse[:40])
    )
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
        {"role": "user", "content": user},
    ]


def generate_category(
    category: str, n_batches: int, graph: dict, do_not_reuse: List[str], dry_run: bool, model: str
) -> List[dict]:
    pairs: List[dict] = []
    for batch_idx in range(n_batches):
        messages = build_messages(category, graph, BATCH_SIZE, do_not_reuse + [p["command"] for p in pairs])
        if dry_run:
            print(f"--- {category} batch {batch_idx} ---")
            print(messages[-1]["content"][:300], "...")
            continue
        result = chat(messages, model=model, temperature=1.0)
        data = unwrap_one_level(result["data"], ["pairs"])
        batch_pairs = data.get("pairs", [])
        for p in batch_pairs:
            p.setdefault("category", category)
            pairs.append(p)
        print(f"  {category} batch {batch_idx}: got {len(batch_pairs)} pairs "
              f"(usage: {result['usage']})")
    return pairs


def clean_command(command: str) -> str:
    """Strip markdown emphasis the model sometimes adds around location phrases."""
    return command.replace("**", "").replace("__", "").strip()


def normalize(command: str) -> str:
    return " ".join(command.strip().lower().split())


def dedupe(pairs: List[dict], seen_norms: List[str]) -> List[dict]:
    kept: List[dict] = []
    for p in pairs:
        cmd = p.get("command")
        if not isinstance(cmd, str) or not cmd.strip():
            continue
        cmd = clean_command(cmd)
        p["command"] = cmd
        norm = normalize(cmd)
        is_dupe = any(norm == s or fuzz.ratio(norm, s) >= 90 for s in seen_norms)
        if is_dupe:
            continue
        seen_norms.append(norm)
        kept.append(p)
    return kept


def validate_expected(pairs: List[dict], canonical_names: List[str], category: str) -> List[dict]:
    valid_set = set(canonical_names) | {"none"}
    out = []
    for p in pairs:
        expected = p.get("expected")
        if category == "adversarial":
            if expected != "none":
                continue
        else:
            if expected not in valid_set or expected == "none":
                continue
        out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "data", "runs", "gen_dataset"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default="ministral-14b-latest")
    args = ap.parse_args()

    with open(ANNOTATIONS_PATH, "r", encoding="utf-8") as f:
        graph = json.load(f)
    canonical_names = [r["name"] for r in graph["rooms"]]
    fewshot_commands = load_fewshot_commands()

    os.makedirs(args.out, exist_ok=True)
    raw_path = os.path.join(args.out, "raw_candidates.jsonl")

    seen_norms = [normalize(c) for c in fewshot_commands]
    all_valid: List[dict] = []

    with open(raw_path, "w", encoding="utf-8") as raw_f:
        for category in RESOLVABLE_CATEGORIES:
            raw = generate_category(
                category, RESOLVABLE_BATCHES, graph, fewshot_commands, args.dry_run, args.model
            )
            if args.dry_run:
                continue
            deduped = dedupe(raw, seen_norms)
            valid = validate_expected(deduped, canonical_names, category)
            print(f"{category}: {len(raw)} generated -> {len(deduped)} deduped -> {len(valid)} valid")
            for p in valid:
                raw_f.write(json.dumps(p) + "\n")
            all_valid.extend(valid)

        adversarial_raw = generate_category(
            "adversarial", ADVERSARIAL_BATCHES, graph, fewshot_commands, args.dry_run, args.model
        )
        if not args.dry_run:
            deduped = dedupe(adversarial_raw, seen_norms)
            valid = validate_expected(deduped, canonical_names, "adversarial")
            print(f"adversarial: {len(adversarial_raw)} generated -> {len(deduped)} deduped -> "
                  f"{len(valid)} valid")
            for p in valid:
                raw_f.write(json.dumps(p) + "\n")
            all_valid.extend(valid)

    if args.dry_run:
        print("dry run complete, no API calls made")
        return

    print(f"total valid candidates: {len(all_valid)}, written to {raw_path}")


if __name__ == "__main__":
    main()
