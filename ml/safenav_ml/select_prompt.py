"""Select the production prompt configuration from Stage B results, update
``config/planner_params.yaml`` and write ``config/prompts/production.txt``
(docs/phase-4-brief.md section 7.4).

    python ml/safenav_ml/select_prompt.py --stage-b-dir data/runs/prompt_study
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROS2_PY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ros2_ws", "src", "semantic_waypoint_planner",
)
sys.path.insert(0, ROS2_PY_PATH)

from safenav_ml.prompt_study import parse_condition  # noqa: E402
from semantic_waypoint_planner.graph import AnnotationGraph  # noqa: E402
from semantic_waypoint_planner.prompt import PromptBuilder  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANNOTATIONS_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "maps", "room_annotations.json"
)
PLANNER_PARAMS_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "config", "planner_params.yaml"
)
PRODUCTION_PROMPT_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "config", "prompts", "production.txt"
)
TEMPLATE_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "config", "prompts", "system_template.txt"
)
FEWSHOT_PATH = os.path.join(
    REPO_ROOT, "ros2_ws", "src", "semantic_waypoint_planner", "config", "prompts", "fewshot.jsonl"
)


def _read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def select_condition(rows: List[Dict[str, str]]) -> Dict[str, str]:
    """Best top1 on the full 500 among GBNF conditions; tie-break by p90_ms; then apply
    section 13's rule (fewest few shot examples within 2 points of the best top1)."""
    gbnf_rows = [r for r in rows if r["condition"].endswith("_gbnf")]
    if not gbnf_rows:
        raise SystemExit("no gbnf conditions found in Stage B summary.csv")

    def top1(r):
        return float(r["top1"]) if r["top1"] not in ("", "None") else -1.0

    best_top1 = max(top1(r) for r in gbnf_rows)
    within_2pts = [r for r in gbnf_rows if best_top1 - top1(r) <= 0.02]

    def fewshot_count(r):
        return parse_condition(r["condition"])["fewshot_count"]

    within_2pts.sort(key=lambda r: (fewshot_count(r), float(r["p90_ms"])))
    return within_2pts[0]


def update_planner_params(condition: Dict[str, str]) -> None:
    parsed = parse_condition(condition["condition"])
    with open(PLANNER_PARAMS_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    replacements = {
        "temperature": f"    temperature: {parsed['temperature']}\n",
        "grammar_on": "    grammar_on: true\n",
        "fewshot_count": f"    fewshot_count: {parsed['fewshot_count']}\n",
    }
    out_lines = []
    for line in lines:
        key = line.strip().split(":")[0]
        if key in replacements:
            out_lines.append(replacements[key])
        else:
            out_lines.append(line)
    with open(PLANNER_PARAMS_PATH, "w", encoding="utf-8") as f:
        f.writelines(out_lines)
    print(f"updated {PLANNER_PARAMS_PATH}: "
          f"temperature={parsed['temperature']}, fewshot_count={parsed['fewshot_count']}, grammar_on=true")


def write_production_prompt(condition: Dict[str, str]) -> None:
    parsed = parse_condition(condition["condition"])
    graph = AnnotationGraph.from_file(ANNOTATIONS_PATH)
    builder = PromptBuilder(graph, TEMPLATE_PATH, FEWSHOT_PATH, fewshot_count=parsed["fewshot_count"])
    system_text = builder.build_system_text()
    header = (
        f"# version: 2\n"
        f"# selected condition: {condition['condition']} (Phase 4 prompt study)\n"
        f"# top1={condition['top1']} top3={condition['top3']} p50_ms={condition['p50_ms']} "
        f"p90_ms={condition['p90_ms']}\n"
    )
    with open(PRODUCTION_PROMPT_PATH, "w", encoding="utf-8") as f:
        f.write(header + system_text)
    print(f"wrote {PRODUCTION_PROMPT_PATH}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-b-dir", default=os.path.join(REPO_ROOT, "data", "runs", "prompt_study"))
    ap.add_argument("--summary-csv", default=None)
    args = ap.parse_args()

    summary_path = args.summary_csv or os.path.join(args.stage_b_dir, "summary.csv")
    rows = _read_csv(summary_path)
    winner = select_condition(rows)
    print(f"selected condition: {winner['condition']} "
          f"(top1={winner['top1']}, top3={winner['top3']}, p90_ms={winner['p90_ms']})")

    update_planner_params(winner)
    write_production_prompt(winner)


if __name__ == "__main__":
    main()
