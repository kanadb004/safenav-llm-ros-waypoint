import llama_cpp
import pytest

from semantic_waypoint_planner.grammar import RELATION_VALUES, build_grammar

NAMES = ["charging_dock", "kitchen", "server_room"]


def _literal(name: str) -> str:
    # GBNF string literal for the JSON-quoted name, e.g. `\"kitchen\"` inside the grammar text.
    return f'\\"{name}\\"'


def test_build_grammar_sorted_and_allow_none():
    grammar_str = build_grammar(NAMES, allow_none=True)
    assert _literal("charging_dock") in grammar_str
    assert _literal("none") in grammar_str
    assert grammar_str.index(_literal("charging_dock")) < grammar_str.index(_literal("kitchen"))
    assert grammar_str.index(_literal("kitchen")) < grammar_str.index(_literal("server_room"))


def test_build_grammar_no_none():
    grammar_str = build_grammar(NAMES, allow_none=False)
    room_value_line = next(l for l in grammar_str.splitlines() if l.startswith("room-value"))
    assert _literal("none") not in room_value_line


def test_build_grammar_empty_raises():
    with pytest.raises(ValueError):
        build_grammar([])


@pytest.mark.parametrize("name", NAMES + ["none"])
def test_every_canonical_name_and_none_present(name):
    grammar_str = build_grammar(NAMES, allow_none=True)
    assert _literal(name) in grammar_str


def test_out_of_graph_name_absent():
    grammar_str = build_grammar(NAMES, allow_none=True)
    assert _literal("cafeteria") not in grammar_str


def test_grammar_compiles():
    grammar_str = build_grammar(NAMES, allow_none=True)
    # raises on malformed GBNF; llama_cpp exposes no string-level accept/reject check without
    # a loaded model context, so true token-level acceptance is proven by the slow model test.
    llama_cpp.LlamaGrammar.from_string(grammar_str, verbose=False)


@pytest.mark.parametrize("relation", RELATION_VALUES)
def test_every_relation_value_present(relation):
    grammar_str = build_grammar(NAMES, allow_none=True)
    assert _literal(relation) in grammar_str


def test_relation_field_present_and_ordered_before_confidence():
    grammar_str = build_grammar(NAMES, allow_none=True)
    assert grammar_str.index('\\"relation\\"') < grammar_str.index('\\"confidence\\"')
    assert grammar_str.index('\\"room\\"') < grammar_str.index('\\"relation\\"')


def test_out_of_relation_set_value_absent():
    grammar_str = build_grammar(NAMES, allow_none=True)
    assert _literal("north_of") not in grammar_str
    assert _literal("inside") not in grammar_str
