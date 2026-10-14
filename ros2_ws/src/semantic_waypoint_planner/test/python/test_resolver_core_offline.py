"""Fast path, edit distance, and feature vector tests that need no model (PLAN.md Phase 3)."""

import ast
import inspect
import os

import pytest
import yaml

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

SHIPPED_MAP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "maps", "room_annotations.json",
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


# ---------------------------------------------------------------------------
# Text anchor fix, resolver level (PLAN.md 11B.2, D64). Uses the shipped graph (not FIXTURE)
# because the extraction rule needs real edges and aliases, and a backend stub pinned to a
# "wrong" model room: the model answers the two-hop answer instead of the anchor, exactly the
# defect 11B.0 found.
# ---------------------------------------------------------------------------

class _PinnedAnswerBackend:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def complete(self, prompt, grammar, **kwargs):
        self.calls.append(grammar)
        return '{"room": "meeting_room_a", "relation": "right_of", "confidence": 0.9}', 1.0, 10

    def reset(self):
        pass


def _shipped_graph_core(monkeypatch, **core_kwargs):
    fake = _PinnedAnswerBackend()
    monkeypatch.setattr(resolver_core_module, "build_backend", lambda *a, **k: fake)
    graph = AnnotationGraph.from_file(SHIPPED_MAP_PATH)
    core = ResolverCore(model_path="unused", graph=graph, fewshot_count=0, **core_kwargs)
    return core


def test_text_anchor_on_resolves_from_command_text(monkeypatch):
    core = _shipped_graph_core(monkeypatch)
    result = core.resolve("Go to the room to the right of the kitchen.", fast_path=False)
    assert result.room == "meeting_room_a"
    assert result.anchor_room == "kitchen"
    assert result.anchor_source == "text"
    assert result.model_room == "meeting_room_a"


def test_text_anchor_off_keeps_pre_fix_double_hop(monkeypatch):
    core = _shipped_graph_core(monkeypatch, text_anchor=False)
    result = core.resolve("Go to the room to the right of the kitchen.", fast_path=False)
    assert result.room == "meeting_room_b"
    assert result.anchor_room == "meeting_room_a"
    assert result.anchor_source == "model"


def test_within_relation_is_not_routed_through_text_anchor(monkeypatch):
    fake = _PinnedAnswerBackend()
    fake.complete = lambda prompt, grammar, **kwargs: (
        '{"room": "coffee_machine", "relation": "within", "confidence": 0.9}', 1.0, 10
    )
    monkeypatch.setattr(resolver_core_module, "build_backend", lambda *a, **k: fake)
    graph = AnnotationGraph.from_file(SHIPPED_MAP_PATH)
    core = ResolverCore(model_path="unused", graph=graph, fewshot_count=0)
    result = core.resolve("take me to the room with the coffee machine", fast_path=False)
    assert result.room == "kitchen"
    assert result.anchor_source == "model"


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


PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLANNER_PARAMS_PATH = os.path.join(PACKAGE_ROOT, "config", "planner_params.yaml")
LLM_RESOLVER_SCRIPT_PATH = os.path.join(PACKAGE_ROOT, "scripts", "llm_resolver.py")


def _declared_text_anchor_default(script_path: str) -> bool:
    """PLAN.md 11C.2: the node's declared default for ``text_anchor``, read from the source by
    AST (``declare_parameter("text_anchor", True)``) so this test needs no rclpy import."""
    with open(script_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=script_path)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "declare_parameter"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "text_anchor"
        ):
            default_arg = node.args[1]
            if isinstance(default_arg, ast.Constant):
                return bool(default_arg.value)
            raise ValueError(f"non-constant text_anchor default: {ast.dump(default_arg)}")
    raise AssertionError("no declare_parameter(\"text_anchor\", ...) call found")


def test_text_anchor_default_agrees_in_yaml_core_and_node():
    """PLAN.md 11C.2 (D65): the shipped default must be the same in every entry point. The
    ``ResolverCore`` constructor default, the node's declared default, and
    ``planner_params.yaml`` must all agree."""
    core_default = inspect.signature(ResolverCore.__init__).parameters["text_anchor"].default
    node_default = _declared_text_anchor_default(LLM_RESOLVER_SCRIPT_PATH)
    with open(PLANNER_PARAMS_PATH, "r", encoding="utf-8") as f:
        yaml_default = yaml.safe_load(f)["llm_resolver_node_py"]["ros__parameters"]["text_anchor"]

    assert core_default is True
    assert node_default is True
    assert yaml_default is True
    assert core_default == node_default == yaml_default


# PLAN.md section 15 (Phase 9): the hardware profile lives beside the sim profile in the same
# file, under a "_hardware" suffixed node name (not wired into a launch file yet, Phase 10
# decides that). These fields are the ones the plan calls out as allowed to differ.
RESOLVER_HARDWARE_DIFF_FIELDS = {"n_threads", "timeout_ms", "backend", "backend_url"}


def _load_planner_params():
    with open(PLANNER_PARAMS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_hardware_and_sim_resolver_profiles_both_load_and_validate():
    params = _load_planner_params()
    sim = params["llm_resolver_node_py"]["ros__parameters"]
    hardware = params["llm_resolver_node_py_hardware"]["ros__parameters"]

    assert hardware["timeout_ms"] == 3000
    assert hardware["backend"] == "http"
    assert hardware["backend_url"] == "http://127.0.0.1:8080"
    assert isinstance(hardware["n_threads"], int) and hardware["n_threads"] > 0


def test_hardware_resolver_profile_differs_from_sim_only_in_documented_fields():
    params = _load_planner_params()
    sim = params["llm_resolver_node_py"]["ros__parameters"]
    hardware = params["llm_resolver_node_py_hardware"]["ros__parameters"]

    assert set(sim) == set(hardware), "hardware profile must declare the same parameter names"
    differing = {key for key in sim if sim[key] != hardware[key]}
    assert differing == RESOLVER_HARDWARE_DIFF_FIELDS


def test_hardware_and_sim_goal_node_timeout_profiles_both_load_and_validate():
    params = _load_planner_params()
    sim = params["semantic_goal_node"]["ros__parameters"]
    hardware = params["semantic_goal_node_hardware"]["ros__parameters"]

    assert sim["default_timeout_ms"] == 300000
    assert hardware["default_timeout_ms"] == 3000
