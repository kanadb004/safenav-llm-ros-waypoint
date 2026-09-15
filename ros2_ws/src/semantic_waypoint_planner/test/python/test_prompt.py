import os

from semantic_waypoint_planner.graph import AnnotationGraph
from semantic_waypoint_planner.prompt import DEFAULT_FEWSHOT_PATH, DEFAULT_TEMPLATE_PATH, PromptBuilder

FIXTURE = {
    "version": 1,
    "facility": "safenav_lab",
    "frame": "map",
    "rooms": [
        {"name": "kitchen", "aliases": ["break room"], "pose": {"x": 0.0, "y": 0.0, "theta": 0.0}},
        {"name": "charging_dock", "aliases": ["dock"], "pose": {"x": 1.0, "y": 1.0, "theta": 0.0}},
    ],
    "edges": [{"from": "kitchen", "to": "charging_dock", "relation": "adjacent"}],
}


def _graph():
    return AnnotationGraph.from_dict(FIXTURE)


def test_template_files_exist():
    assert os.path.exists(DEFAULT_TEMPLATE_PATH)
    assert os.path.exists(DEFAULT_FEWSHOT_PATH)


def test_template_has_version():
    builder = PromptBuilder(_graph(), fewshot_count=0)
    assert builder.template_version == "1"


def test_locations_block_lists_aliases():
    builder = PromptBuilder(_graph(), fewshot_count=0)
    block = builder.locations_block()
    assert "kitchen: break room" in block
    assert "charging_dock: dock" in block


def test_adjacency_block_mentions_edge():
    builder = PromptBuilder(_graph(), fewshot_count=0)
    block = builder.adjacency_block()
    assert "adjacent" in block


def test_fewshot_zero_is_empty():
    builder = PromptBuilder(_graph(), fewshot_count=0)
    assert builder.fewshot_block() == ""


def test_fewshot_count_limits_examples():
    builder = PromptBuilder(_graph(), fewshot_count=5)
    block = builder.fewshot_block()
    assert block.count("Command:") == 5


def test_build_prompt_has_chat_markers():
    builder = PromptBuilder(_graph(), fewshot_count=0)
    prompt = builder.build_prompt("go to the kitchen")
    assert prompt.startswith("<|system|>\n")
    assert "<|user|>\ngo to the kitchen<|end|>\n<|assistant|>\n" in prompt
