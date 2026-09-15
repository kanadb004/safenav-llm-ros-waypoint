"""Prompt construction for the LLM resolver (PLAN.md Phase 3 scope).

Builds the Phi-3 instruct chat prompt from a versioned template file: system text (facility
name, task, known locations with aliases, adjacency sentences from the graph's edges), an
optional block of curated few shot examples, and the user command. ROS free.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional

from .graph import AnnotationGraph

def _default_prompt_dir() -> str:
    # When installed, this module lives under .../lib/pythonX/dist-packages/semantic_waypoint_
    # planner/, a different install tree than the config/ share directory, so a path relative
    # to __file__ only works from the source tree. Prefer ament's share directory lookup and
    # fall back to the source-tree layout for host use without a sourced ROS environment.
    try:
        from ament_index_python.packages import get_package_share_directory

        return os.path.join(get_package_share_directory("semantic_waypoint_planner"), "config", "prompts")
    except Exception:
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(package_dir, "config", "prompts")


_PROMPT_DIR = _default_prompt_dir()
DEFAULT_TEMPLATE_PATH = os.path.join(_PROMPT_DIR, "system_template.txt")
DEFAULT_FEWSHOT_PATH = os.path.join(_PROMPT_DIR, "fewshot.jsonl")


@dataclass
class FewshotExample:
    command: str
    room: str
    confidence: float


def load_template(path: str) -> "tuple[str, str]":
    """Return (version, body). The template's first line is ``# version: <string>``."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not lines or not lines[0].startswith("# version:"):
        raise ValueError(f"template {path} missing '# version:' header on line 1")
    version = lines[0].split(":", 1)[1].strip()
    body = "\n".join(lines[1:])
    return version, body


def load_fewshot(path: str) -> List[FewshotExample]:
    if not os.path.exists(path):
        return []
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            examples.append(
                FewshotExample(
                    command=row["command"], room=row["room"], confidence=float(row["confidence"])
                )
            )
    return examples


class PromptBuilder:
    """Renders the system prompt and full chat prompt for a given annotation graph."""

    def __init__(
        self,
        graph: AnnotationGraph,
        template_path: str = DEFAULT_TEMPLATE_PATH,
        fewshot_path: str = DEFAULT_FEWSHOT_PATH,
        fewshot_count: int = 0,
    ):
        self.graph = graph
        self.template_version, self._template_body = load_template(template_path)
        self._fewshot = load_fewshot(fewshot_path)
        self.fewshot_count = fewshot_count

    def locations_block(self) -> str:
        lines = []
        for room in self.graph.rooms:
            aliases = ", ".join(room.aliases) if room.aliases else "(no aliases)"
            lines.append(f"- {room.name}: {aliases}")
        return "\n".join(lines)

    def adjacency_block(self) -> str:
        sentences = []
        for room in self.graph.rooms:
            text = self.graph.adjacency_text(room.name)
            if text and not text.endswith("no recorded adjacency."):
                sentences.append(text)
        return "\n".join(sentences) if sentences else "No spatial relationships recorded."

    def fewshot_block(self) -> str:
        if self.fewshot_count <= 0 or not self._fewshot:
            return ""
        chosen = self._fewshot[: self.fewshot_count]
        lines = ["Examples:"]
        for ex in chosen:
            answer = json.dumps({"room": ex.room, "confidence": ex.confidence})
            lines.append(f'Command: "{ex.command}"\nAnswer: {answer}')
        return "\n".join(lines) + "\n"

    def build_system_text(self) -> str:
        return self._template_body.format(
            facility=self.graph.facility or "safenav_lab",
            locations_block=self.locations_block(),
            adjacency_block=self.adjacency_block(),
            fewshot_block=self.fewshot_block(),
        )

    def build_prompt(self, command: str) -> str:
        system_text = self.build_system_text()
        return f"<|system|>\n{system_text}<|end|>\n<|user|>\n{command}<|end|>\n<|assistant|>\n"
