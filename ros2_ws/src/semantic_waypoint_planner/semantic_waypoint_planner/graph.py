"""ROS free annotation graph core.

Loads, validates, and queries the ``room_annotations.json`` schema described in
``docs/PLAN.md`` section 12.7. Has no ROS imports so it can be exercised on the host and
reused by ``annotation_map_node`` (via the JSON on disk), ``annotate_map.py``, and the
Phase 3 prompt builder.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

SCHEMA_VERSION = 1


class GraphValidationError(ValueError):
    """Raised when a room_annotations.json document fails validation."""


@dataclass
class Room:
    name: str
    aliases: List[str] = field(default_factory=list)
    pose: Dict[str, float] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    parent: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "pose": dict(self.pose),
            "tags": list(self.tags),
            "parent": self.parent,
        }


@dataclass
class Edge:
    from_: str
    to: str
    relation: str

    def to_dict(self) -> dict:
        return {"from": self.from_, "to": self.to, "relation": self.relation}


class AnnotationGraph:
    """In memory, validated view of an annotation JSON document."""

    def __init__(self, facility: str, frame: str, rooms: List[Room], edges: List[Edge]):
        self.facility = facility
        self.frame = frame
        self.rooms: List[Room] = rooms
        self.edges: List[Edge] = edges
        self._by_name: Dict[str, Room] = {r.name: r for r in rooms}
        self._alias_index: Dict[str, str] = {}
        for r in rooms:
            for alias in r.aliases:
                self._alias_index[alias] = r.name

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict) -> "AnnotationGraph":
        validate(data)
        rooms = [
            Room(
                name=r["name"],
                aliases=list(r.get("aliases", [])),
                pose=dict(r["pose"]),
                tags=list(r.get("tags", [])),
                parent=r.get("parent", ""),
            )
            for r in data["rooms"]
        ]
        edges = [
            Edge(from_=e["from"], to=e["to"], relation=e["relation"])
            for e in data.get("edges", [])
        ]
        return cls(
            facility=data.get("facility", ""),
            frame=data.get("frame", "map"),
            rooms=rooms,
            edges=edges,
        )

    @classmethod
    def from_file(cls, path: str) -> "AnnotationGraph":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        return {
            "version": SCHEMA_VERSION,
            "facility": self.facility,
            "frame": self.frame,
            "rooms": [r.to_dict() for r in self.rooms],
            "edges": [e.to_dict() for e in self.edges],
        }

    def save(self, path: str) -> None:
        """Atomic write: write to a temp file in the same directory, then rename."""
        data = self.to_dict()
        # Validate before persisting so a bad in-memory state never hits disk.
        validate(data)
        directory = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".room_annotations.", suffix=".json.tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @property
    def canonical_names(self) -> List[str]:
        return [r.name for r in self.rooms]

    @property
    def all_aliases(self) -> List[str]:
        aliases: List[str] = []
        for r in self.rooms:
            aliases.extend(r.aliases)
        return aliases

    def get_room(self, name: str) -> Optional[Room]:
        return self._by_name.get(name)

    def resolve_alias(self, text: str) -> Optional[str]:
        """Return the canonical name for an exact canonical name or alias match, else None."""
        if text in self._by_name:
            return text
        return self._alias_index.get(text)

    def adjacency_text(self, name: str) -> str:
        """Render a sentence describing the edges touching ``name`` (used by Phase 3 prompts)."""
        room = self.get_room(name)
        if room is None:
            return ""
        by_relation: Dict[str, List[str]] = {}
        for e in self.edges:
            if e.from_ == name:
                by_relation.setdefault(e.relation, []).append(e.to)
            elif e.to == name and e.relation in ("adjacent", "near"):
                # symmetric relations also read naturally from the other endpoint
                by_relation.setdefault(e.relation, []).append(e.from_)
        if not by_relation:
            return f"{name} has no recorded adjacency."
        clauses = []
        for relation, others in by_relation.items():
            others_text = ", ".join(sorted(set(others)))
            clauses.append(f"{relation.replace('_', ' ')} {others_text}")
        return f"{name} is " + "; ".join(clauses) + "."

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------
    def add_room(self, room: Room) -> None:
        """Add a room, validating the resulting document. Raises GraphValidationError."""
        if room.name in self._by_name:
            raise GraphValidationError(f"duplicate room name: {room.name}")
        candidate = self.to_dict()
        candidate["rooms"].append(room.to_dict())
        validate(candidate)
        self.rooms.append(room)
        self._by_name[room.name] = room
        for alias in room.aliases:
            self._alias_index[alias] = room.name


def validate(data: dict) -> None:
    """Validate a room_annotations.json document. Raises GraphValidationError on failure."""
    if not isinstance(data, dict):
        raise GraphValidationError("document must be a JSON object")
    if "rooms" not in data or not isinstance(data["rooms"], list):
        raise GraphValidationError("document must have a 'rooms' array")
    if not data["rooms"]:
        raise GraphValidationError("'rooms' must not be empty")

    seen_names = set()
    seen_aliases = set()
    for i, r in enumerate(data["rooms"]):
        if not isinstance(r, dict):
            raise GraphValidationError(f"rooms[{i}] must be an object")
        name = r.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise GraphValidationError(
                f"rooms[{i}] name {name!r} must be lowercase snake_case"
            )
        if name in seen_names:
            raise GraphValidationError(f"duplicate room name: {name}")
        seen_names.add(name)

        aliases = r.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
            raise GraphValidationError(f"rooms[{i}] '{name}' aliases must be a list of strings")
        for alias in aliases:
            if alias != alias.lower():
                raise GraphValidationError(f"alias '{alias}' must be lowercase")
            if alias in seen_aliases:
                raise GraphValidationError(f"duplicate alias: {alias}")
            if alias in seen_names or any(alias == n for n in seen_names):
                raise GraphValidationError(f"alias '{alias}' collides with a canonical name")
            seen_aliases.add(alias)

        pose = r.get("pose")
        if not isinstance(pose, dict):
            raise GraphValidationError(f"rooms[{i}] '{name}' missing pose")
        for key in ("x", "y", "theta"):
            value = pose.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise GraphValidationError(
                    f"rooms[{i}] '{name}' pose.{key} must be a finite number"
                )

    # aliases must not collide with any canonical name declared anywhere in the file,
    # including ones seen later than the alias itself
    all_names = seen_names
    for r in data["rooms"]:
        for alias in r.get("aliases", []):
            if alias in all_names:
                raise GraphValidationError(f"alias '{alias}' collides with a canonical name")

    edges = data.get("edges", [])
    if not isinstance(edges, list):
        raise GraphValidationError("'edges' must be a list")
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            raise GraphValidationError(f"edges[{i}] must be an object")
        for key in ("from", "to", "relation"):
            if key not in e or not isinstance(e[key], str):
                raise GraphValidationError(f"edges[{i}] missing '{key}'")
        if e["from"] not in all_names:
            raise GraphValidationError(f"edges[{i}] unknown endpoint 'from': {e['from']}")
        if e["to"] not in all_names:
            raise GraphValidationError(f"edges[{i}] unknown endpoint 'to': {e['to']}")
