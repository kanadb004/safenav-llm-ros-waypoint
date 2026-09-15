"""Validates the committed benchmark files (PLAN.md Phase 4 DoD). Skips if the files have not
been generated yet (this phase's own build step writes them before this test can pass)."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_500 = REPO_ROOT / "data" / "benchmark" / "synthetic_500.jsonl"
ADVERSARIAL_50 = REPO_ROOT / "data" / "benchmark" / "adversarial_50.jsonl"
FEWSHOT = (
    REPO_ROOT / "ros2_ws" / "src" / "semantic_waypoint_planner" / "config" / "prompts"
    / "fewshot.jsonl"
)
ANNOTATIONS = (
    REPO_ROOT / "ros2_ws" / "src" / "semantic_waypoint_planner" / "maps"
    / "room_annotations.json"
)

pytestmark = pytest.mark.skipif(
    not SYNTHETIC_500.exists(), reason="synthetic_500.jsonl not generated yet"
)


def _load_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _normalize(command):
    return " ".join(command.strip().lower().split())


def _canonical_names():
    data = json.loads(ANNOTATIONS.read_text())
    return {r["name"] for r in data["rooms"]}


def test_synthetic_500_row_count():
    rows = _load_jsonl(SYNTHETIC_500)
    assert len(rows) == 500


def test_synthetic_500_all_reviewed():
    rows = _load_jsonl(SYNTHETIC_500)
    assert all(r["reviewed"] is True for r in rows)


def test_synthetic_500_no_duplicate_commands():
    rows = _load_jsonl(SYNTHETIC_500)
    normed = [_normalize(r["command"]) for r in rows]
    assert len(normed) == len(set(normed))


def test_synthetic_500_disjoint_from_fewshot():
    rows = _load_jsonl(SYNTHETIC_500)
    fewshot = _load_jsonl(FEWSHOT)
    fewshot_norms = {_normalize(r["command"]) for r in fewshot}
    benchmark_norms = {_normalize(r["command"]) for r in rows}
    assert not (fewshot_norms & benchmark_norms)


def test_synthetic_500_expected_in_graph_or_none():
    rows = _load_jsonl(SYNTHETIC_500)
    names = _canonical_names()
    for r in rows:
        assert r["expected"] == "none" or r["expected"] in names


def test_synthetic_500_category_counts():
    rows = _load_jsonl(SYNTHETIC_500)
    counts = {}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    assert counts.get("adversarial") == 45
    resolvable = {"direct", "alias", "spatial", "functional", "negation", "abbreviation", "multi_hop"}
    for cat in resolvable:
        assert counts.get(cat) == 65


def test_adversarial_50_row_count():
    rows = _load_jsonl(ADVERSARIAL_50)
    assert len(rows) == 50
    assert all(r["expected"] == "none" for r in rows)
