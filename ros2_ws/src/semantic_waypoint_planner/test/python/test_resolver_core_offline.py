"""Fast path, edit distance, and feature vector tests that need no model (PLAN.md Phase 3)."""

import pytest

from semantic_waypoint_planner import resolver_core as resolver_core_module
from semantic_waypoint_planner.graph import AnnotationGraph
from semantic_waypoint_planner.resolver_core import (
    ResolveResult,
    ResolverCore,
    fast_path_match,
    features,
    min_edit_distance,
    normalize_command,
)

FIXTURE = {
    "version": 1,
    "facility": "safenav_lab",
    "frame": "map",
    "rooms": [
        {
            "name": "kitchen",
            "aliases": ["break room", "kitchenette"],
            "pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
        },
        {
            "name": "charging_dock",
            "aliases": ["dock", "charger"],
            "pose": {"x": 1.0, "y": 1.0, "theta": 0.0},
        },
    ],
    "edges": [],
}


def _graph():
    return AnnotationGraph.from_dict(FIXTURE)


def test_normalize_collapses_whitespace_and_case():
    assert normalize_command("  Go   TO the Kitchen  ") == "go to the kitchen"


@pytest.mark.parametrize(
    "command,expected",
    [
        ("kitchen", "kitchen"),
        ("break room", "kitchen"),
        ("dock", "charging_dock"),
        ("go to the kitchen", "kitchen"),
        ("navigate to break room", "kitchen"),
        ("take me to the charger", "charging_dock"),
        ("head to dock", "charging_dock"),
    ],
)
def test_fast_path_matches(command, expected):
    assert fast_path_match(_graph(), command) == expected


@pytest.mark.parametrize(
    "command",
    ["somewhere I can charge the robot", "go to the cafeteria", ""],
)
def test_fast_path_misses(command):
    assert fast_path_match(_graph(), command) is None


def test_min_edit_distance_exact_match_is_zero():
    assert min_edit_distance("kitchen", ["break room"], "go to the kitchen now") == 0


def test_min_edit_distance_uses_alias():
    assert min_edit_distance("kitchen", ["break room"], "please visit the break room") == 0


def test_min_edit_distance_none_room_is_command_length():
    norm = normalize_command("go to the cafeteria")
    assert min_edit_distance(None, [], norm) == len(norm)


def test_parse_answer_well_formed_json_with_relation():
    room, relation, confidence = ResolverCore._parse_answer(
        '{"room": "kitchen", "relation": "left_of", "confidence": 0.85}'
    )
    assert room == "kitchen"
    assert relation == "left_of"
    assert confidence == pytest.approx(0.85)


def test_parse_answer_missing_relation_defaults_to_none():
    room, relation, confidence = ResolverCore._parse_answer('{"room": "kitchen", "confidence": 0.9}')
    assert room == "kitchen"
    assert relation == "none"
    assert confidence == pytest.approx(0.9)


def test_parse_answer_garbled_text_falls_back_to_regex():
    room, relation, confidence = ResolverCore._parse_answer(
        'blah "room": "kitchen", "relation": "near", "confidence": 0.7 blah'
    )
    assert room == "kitchen"
    assert relation == "near"
    assert confidence == pytest.approx(0.7)


def test_parse_answer_fully_garbled_defaults():
    room, relation, confidence = ResolverCore._parse_answer("not json at all")
    assert room is None
    assert relation == "none"
    assert confidence == 0.0


class _FakeBackend:
    """Records every grammar string it is handed; returns a canned, well-formed v2 answer
    regardless, since the point of this fake is to observe grammar selection, not parsing."""

    def __init__(self, *args, **kwargs):
        self.calls = []

    def complete(self, prompt, grammar, **kwargs):
        self.calls.append(grammar)
        return '{"room": "kitchen", "relation": "none", "confidence": 0.9}', 1.0, 10

    def reset(self):
        pass


@pytest.fixture()
def fake_backend_core(monkeypatch):
    fake = _FakeBackend()
    monkeypatch.setattr(resolver_core_module, "build_backend", lambda *a, **k: fake)
    core = ResolverCore(model_path="unused", graph=_graph(), fewshot_count=0)
    return core, fake


# ---------------------------------------------------------------------------
# Cue gating grammar selection (PLAN.md 8A.1, D38)
# ---------------------------------------------------------------------------

def test_cue_free_command_takes_v1_grammar(fake_backend_core):
    core, fake = fake_backend_core
    core.resolve("go to the server room", fast_path=False)
    assert len(fake.calls) == 1
    assert fake.calls[0] == core.grammar_str_v1
    assert fake.calls[0] != core.grammar_str


def test_cued_command_takes_v2_grammar(fake_backend_core):
    core, fake = fake_backend_core
    core.resolve("go to the room to the left of the kitchen", fast_path=False)
    assert len(fake.calls) == 1
    assert fake.calls[0] == core.grammar_str
    assert fake.calls[0] != core.grammar_str_v1


def test_cue_free_command_forces_relation_none(fake_backend_core):
    core, _fake = fake_backend_core
    result = core.resolve("go to the server room", fast_path=False)
    assert result.relation == "none"
    assert result.grammar_version == "v1"


def test_cued_command_reports_v2_grammar_version(fake_backend_core):
    core, _fake = fake_backend_core
    result = core.resolve("go to the room to the left of the kitchen", fast_path=False)
    assert result.grammar_version == "v2"


def test_cue_gating_disabled_always_uses_v2(monkeypatch):
    fake = _FakeBackend()
    monkeypatch.setattr(resolver_core_module, "build_backend", lambda *a, **k: fake)
    core = ResolverCore(model_path="unused", graph=_graph(), fewshot_count=0, cue_gating=False)
    core.resolve("go to the server room", fast_path=False)
    assert fake.calls[0] == core.grammar_str


def test_features_vector_order():
    result = ResolveResult(
        room="kitchen",
        raw_confidence=0.9,
        reasoning="",
        token_entropy=0.1,
        room_ranking=[("kitchen", 0.9)],
        latency_ms=5.0,
        mode="fast_path",
        out_of_graph=False,
        raw_text="",
    )
    vec = features(result, "go to the kitchen", 30, aliases=["break room"])
    assert len(vec) == 5
    assert vec[0] == 0.9
    assert vec[1] == 0.1
    assert vec[2] == 30.0
    assert vec[3] == float(len(normalize_command("go to the kitchen")))
    assert vec[4] == 0.0
