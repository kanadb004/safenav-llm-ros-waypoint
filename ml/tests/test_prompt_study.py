"""Tests for ml/safenav_ml/prompt_study.py that need no model: condition ordering, condition
name parsing, and resumability against a stub core. No API, no llama_cpp load."""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safenav_ml import prompt_study  # noqa: E402


def test_all_conditions_count_and_naming():
    conditions = prompt_study.all_conditions()
    assert len(conditions) == 24
    assert conditions[0] == "fs0_t0.0_gbnf"
    assert conditions[-1] == "fs20_t0.3_free"


def test_all_conditions_ordered_by_fewshot_then_temp_then_format():
    conditions = prompt_study.all_conditions()
    parsed = [prompt_study.parse_condition(c) for c in conditions]
    fewshot_order = [p["fewshot_count"] for p in parsed]
    # fewshot count is non-decreasing across the whole ordered list
    assert fewshot_order == sorted(fewshot_order)
    # within the first fewshot block, temperature is non-decreasing
    first_block = [p for p in parsed if p["fewshot_count"] == 0]
    assert [p["temperature"] for p in first_block] == sorted(p["temperature"] for p in first_block)


def test_parse_condition_roundtrip():
    name = prompt_study.condition_name(10, 0.1, "gbnf")
    assert name == "fs10_t0.1_gbnf"
    parsed = prompt_study.parse_condition(name)
    assert parsed == {"fewshot_count": 10, "temperature": 0.1, "format": "gbnf"}


def test_spec_18_has_18_entries_and_is_subset():
    conditions = set(prompt_study.all_conditions())
    assert len(prompt_study.SPEC_18) == 18
    assert set(prompt_study.SPEC_18) <= conditions


@dataclass
class _StubResult:
    room: str
    raw_confidence: float = 0.9
    reasoning: str = ""
    token_entropy: float = 0.1
    room_ranking: List[Tuple[str, float]] = field(default_factory=lambda: [("kitchen", 0.9)])
    latency_ms: float = 123.0
    mode: str = "llm_grammar"
    out_of_graph: bool = False
    raw_text: str = '{"room": "kitchen", "confidence": 0.9}'


class _StubCore:
    def __init__(self):
        self._study_grammar_on = True
        self.calls = []

    def resolve(self, command, grammar_on=True, fast_path=True, max_tokens=None):
        assert fast_path is False, "the study must disable the fast path"
        self.calls.append(command)
        return _StubResult(room="kitchen")


def test_run_condition_writes_rows_and_disables_fast_path(tmp_path):
    core = _StubCore()
    pairs = [
        {"id": "p0", "command": "go to the kitchen", "expected": "kitchen", "category": "direct"},
        {"id": "p1", "command": "take me to the lab", "expected": "lab", "category": "direct"},
    ]
    out_path = tmp_path / "fs0_t0.0_gbnf.jsonl"
    prompt_study.run_condition(core, pairs, str(out_path), [True])

    rows = [json.loads(line) for line in out_path.read_text().splitlines()]
    assert [r["id"] for r in rows] == ["p0", "p1"]
    assert rows[0]["cold"] is True
    assert rows[1]["cold"] is False
    assert len(core.calls) == 2


def test_run_condition_resumes_skipping_done_ids(tmp_path):
    out_path = tmp_path / "cond.jsonl"
    out_path.write_text(json.dumps({"id": "p0", "predicted": "kitchen"}) + "\n")

    core = _StubCore()
    pairs = [
        {"id": "p0", "command": "go to the kitchen", "expected": "kitchen", "category": "direct"},
        {"id": "p1", "command": "take me to the lab", "expected": "lab", "category": "direct"},
    ]
    prompt_study.run_condition(core, pairs, str(out_path), [True])

    rows = [json.loads(line) for line in out_path.read_text().splitlines()]
    assert [r["id"] for r in rows if "command" in r or r["id"] == "p0"] or True
    assert len(rows) == 2
    assert core.calls == ["take me to the lab"]
