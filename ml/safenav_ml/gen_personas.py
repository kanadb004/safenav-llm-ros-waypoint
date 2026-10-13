"""Generate the Phase 7 simulated deployment logs (PLAN.md section 10, docs/archive/PLAN-v1.md
section 10) with ``ministral-14b-latest`` over the Mistral REST API. No SDK, temperature 1.0.

Five non-expert personas (admin staff x2, non-robotics PhD students x2, one undergraduate from
another department), each of whom "knows the robot has 30 locations but not the exact names".
Session 1 is 5 x 40 = 200 commands (training), session 2 is 5 x 20 = 100 commands (evaluation).
Categories are balanced the way the Phase 4 benchmark's resolvable categories are (direct,
alias, spatial, functional, negation, abbreviation, multi_hop); there is no adversarial category
here because every row is labeled with a real intended location (docs/archive/PLAN-v1.md
section 10). Both sessions are generated from one combined pool per persona/category so that
disjointness between session 1 and session 2 is structural, then checked by normalized string
equality and a fuzzy threshold against each other and against the 500 benchmark.

Usage:
    python ml/safenav_ml/gen_personas.py --dry-run
    python ml/safenav_ml/gen_personas.py
"""

from __future__ import annotations

import argparse
import json
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
BENCHMARK_500 = os.path.join(REPO_ROOT, "data", "benchmark", "synthetic_500.jsonl")
OUT_DIR = os.path.join(REPO_ROOT, "data", "calibration")

CATEGORIES = ["direct", "alias", "spatial", "functional", "negation", "abbreviation", "multi_hop"]
# Session counts per persona, split across the 7 categories, sized as evenly as possible.
SESSION1_COUNTS = [6, 6, 6, 6, 6, 5, 5]  # sums to 40
SESSION2_COUNTS = [3, 3, 3, 3, 3, 3, 2]  # sums to 20
SURPLUS = 4

PERSONAS = [
    {"id": "admin_1", "role": "admin staff",
     "voice": "a facilities administrator who books rooms and handles deliveries all day"},
    {"id": "admin_2", "role": "admin staff",
     "voice": "a front-desk administrator who greets visitors and routes them around the building"},
    {"id": "phd_1", "role": "non-robotics PhD student",
     "voice": "a chemistry PhD student who is in the building constantly but has never worked with robots"},
    {"id": "phd_2", "role": "non-robotics PhD student",
     "voice": "a sociology PhD student who occasionally needs the robot to carry something between rooms"},
    {"id": "undergrad_1", "role": "undergraduate from another department",
     "voice": "an undergraduate economics major visiting for a one-off project meeting, unfamiliar with the layout"},
]

SYSTEM_INSTRUCTIONS = """You are generating simulated deployment commands for a semantic \
waypoint resolver robot at a facility called "safenav_lab". The robot understands exactly the \
closed list of locations given below (canonical names, aliases, tags, and spatial edges) and \
nothing else. You are writing as a specific persona: {voice}. This person knows the robot \
serves roughly 30 locations in the building but does not know the exact canonical names or the \
full alias list, so their phrasing should sound like a real person describing where they want \
to go, not like someone reading off the location list. For the requested category, generate \
natural-language navigation commands this persona might realistically give the robot, each \
paired with the single canonical location name the command should resolve to. Vary phrasing, \
sentence length, and politeness, consistent with the persona's voice. Do not reuse any command \
from the "do not reuse" list. Respond as a JSON object: \
{{"pairs": [{{"command": str, "intended_room": str, "rationale": str}}, ...]}} with exactly the \
requested number of pairs. "rationale" is one short sentence on why "intended_room" follows \
from the command."""

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
}


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


def normalize(command: str) -> str:
    return " ".join(command.strip().lower().split())


def clean_command(command: str) -> str:
    return command.replace("**", "").replace("__", "").strip()


def build_messages(
    persona: dict, category: str, graph: dict, n: int, do_not_reuse: List[str]
) -> List[Dict[str, str]]:
    system = SYSTEM_INSTRUCTIONS.format(voice=persona["voice"])
    user = (
        f"{render_graph_block(graph)}\n\n"
        f"Category: {category}\n{CATEGORY_PROMPTS[category]}\n\n"
        f"Generate exactly {n} pairs for this category.\n\n"
        "Do not reuse any of these commands (already used elsewhere):\n"
        + "\n".join(f"- {c}" for c in do_not_reuse[:40])
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


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


def validate(pairs: List[dict], canonical_names: List[str]) -> List[dict]:
    valid_set = set(canonical_names)
    return [p for p in pairs if p.get("intended_room") in valid_set]


def load_benchmark_norms() -> List[str]:
    norms = []
    with open(BENCHMARK_500, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            norms.append(normalize(json.loads(line)["command"]))
    return norms


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default="ministral-14b-latest")
    args = ap.parse_args()

    with open(ANNOTATIONS_PATH, "r", encoding="utf-8") as f:
        graph = json.load(f)
    canonical_names = [r["name"] for r in graph["rooms"]]

    seen_norms = [] if args.dry_run else load_benchmark_norms()
    session1: List[dict] = []
    session2: List[dict] = []

    for persona in PERSONAS:
        for category, c1, c2 in zip(CATEGORIES, SESSION1_COUNTS, SESSION2_COUNTS):
            needed = c1 + c2
            if args.dry_run:
                combined_n = needed + SURPLUS
                messages = build_messages(persona, category, graph, combined_n, seen_norms)
                print(f"--- {persona['id']} / {category} (n={combined_n}) ---")
                print(messages[-1]["content"][:300], "...")
                continue

            valid: List[dict] = []
            surplus = SURPLUS
            for attempt in range(3):
                still_need = needed - len(valid)
                if still_need <= 0:
                    break
                request_n = still_need + surplus
                messages = build_messages(persona, category, graph, request_n, seen_norms)
                result = chat(messages, model=args.model, temperature=1.0)
                data = unwrap_one_level(result["data"], ["pairs"])
                raw_pairs = data.get("pairs", [])
                for p in raw_pairs:
                    p["category"] = category
                    p["persona"] = persona["id"]
                deduped = dedupe(raw_pairs, seen_norms)
                new_valid = validate(deduped, canonical_names)
                valid.extend(new_valid)
                print(f"{persona['id']} / {category} (attempt {attempt}): "
                      f"{len(raw_pairs)} generated -> {len(deduped)} deduped -> "
                      f"{len(new_valid)} valid (total {len(valid)}/{needed})")
                surplus = max(surplus, still_need)  # widen the ask if the model is thin

            if len(valid) < needed:
                raise RuntimeError(
                    f"not enough valid pairs for {persona['id']}/{category} after 3 attempts: "
                    f"got {len(valid)}, need {needed}"
                )

            for p in valid[:c1]:
                p["session"] = 1
                session1.append(p)
            for p in valid[c1:c1 + c2]:
                p["session"] = 2
                session2.append(p)

    if args.dry_run:
        print("dry run complete, no API calls made")
        return

    os.makedirs(args.out_dir, exist_ok=True)
    write_session(os.path.join(args.out_dir, "session1_sim.jsonl"), session1)
    write_session(os.path.join(args.out_dir, "session2_sim.jsonl"), session2)
    print(f"session1: {len(session1)} rows, session2: {len(session2)} rows")


def write_session(path: str, rows: List[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            out = {
                "command": row["command"],
                "intended_room": row["intended_room"],
                "category": row["category"],
                "persona": row["persona"],
            }
            f.write(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
