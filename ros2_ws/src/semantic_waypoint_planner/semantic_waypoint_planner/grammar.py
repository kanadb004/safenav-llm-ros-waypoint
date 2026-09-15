"""GBNF grammar generation for the closed room-name output (PLAN.md section 12.6).

ROS free so it can be exercised on the host and reused by the C++ ``grammar_builder`` parity
test in Phase 5 (same canonical names must produce the same literal set, sorted).
"""

from __future__ import annotations

from typing import Iterable, List


def _json_escape(name: str) -> str:
    return name.replace("\\", "\\\\").replace('"', '\\"')


def build_grammar(canonical_names: Iterable[str], allow_none: bool = True) -> str:
    """Build the GBNF grammar string of PLAN.md section 12.6.

    ``room-value`` accepts exactly the sorted canonical names (plus the ``"none"`` sentinel
    when ``allow_none``) and nothing else, so the sampler structurally cannot emit a name
    outside the annotation graph.
    """
    names = sorted(set(canonical_names))
    if not names:
        raise ValueError("canonical_names must not be empty")

    literals: List[str] = [f'"\\"{_json_escape(n)}\\""' for n in names]
    if allow_none:
        literals.append('"\\"none\\""')

    return (
        'root ::= "{" ws "\\"room\\"" ws ":" ws room-value "," ws "\\"confidence\\"" ws ":" '
        'ws confidence-value ws "}"\n'
        f"room-value ::= {' | '.join(literals)}\n"
        'confidence-value ::= [0-9] "." [0-9] [0-9]\n'
        'ws ::= [ \\t\\n]*\n'
    )
