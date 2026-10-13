"""GBNF grammar generation for the closed room-name output (PLAN.md section 12.6).

ROS free so it can be exercised on the host and reused by the C++ ``grammar_builder`` parity
test in Phase 5 (same canonical names must produce the same literal set, sorted).
"""

from __future__ import annotations

from typing import Iterable, List

# PLAN.md section 12.6, v2 (D29). "none" means the current (v1) behaviour: ``room`` is the
# answer. Anything else means ``room`` is the anchor and relations.py computes the hop target.
RELATION_VALUES = ("none", "left_of", "right_of", "adjacent", "near", "within")


def _json_escape(name: str) -> str:
    return name.replace("\\", "\\\\").replace('"', '\\"')


def build_grammar(canonical_names: Iterable[str], allow_none: bool = True) -> str:
    """Build the GBNF grammar string of PLAN.md section 12.6 (v2, D29).

    ``room-value`` accepts exactly the sorted canonical names (plus the ``"none"`` sentinel
    when ``allow_none``) and nothing else, so the sampler structurally cannot emit a name
    outside the annotation graph. ``relation-value`` accepts exactly the closed relation set.
    """
    names = sorted(set(canonical_names))
    if not names:
        raise ValueError("canonical_names must not be empty")

    literals: List[str] = [f'"\\"{_json_escape(n)}\\""' for n in names]
    if allow_none:
        literals.append('"\\"none\\""')

    relation_literals = [f'"\\"{r}\\""' for r in RELATION_VALUES]

    return (
        'root ::= "{" ws "\\"room\\"" ws ":" ws room-value ","'
        ' ws "\\"relation\\"" ws ":" ws relation-value ","'
        ' ws "\\"confidence\\"" ws ":" ws confidence-value ws "}"\n'
        f"room-value ::= {' | '.join(literals)}\n"
        f"relation-value ::= {' | '.join(relation_literals)}\n"
        'confidence-value ::= [0-9] "." [0-9] [0-9]\n'
        'ws ::= [ \\t\\n]*\n'
    )
