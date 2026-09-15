"""Pure metric functions over lists of benchmark result row dicts (PLAN.md Phase 4,
docs/phase-4-brief.md section 5). No ROS, no model, no API calls; unit tested with a toy set.

A row is a dict with at least: ``expected`` (canonical name or ``"none"``), ``predicted``
(canonical name, ``"none"``, or ``None`` for unparseable output), ``category``,
``top_k_rooms`` (list, best first), ``out_of_graph`` (bool), ``malformed`` (bool),
``latency_ms`` (float), ``cold`` (bool).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

Row = Dict[str, object]


def _is_adversarial(row: Row) -> bool:
    return row.get("expected") == "none"


def _abstained(row: Row) -> bool:
    return row.get("predicted") in (None, "none")


def top1(rows: Sequence[Row]) -> Optional[float]:
    """predicted == expected; adversarial rows are correct iff the system abstained."""
    if not rows:
        return None
    correct = 0
    for row in rows:
        if _is_adversarial(row):
            correct += int(_abstained(row))
        else:
            correct += int(row.get("predicted") == row.get("expected"))
    return correct / len(rows)


def top3(rows: Sequence[Row]) -> Optional[float]:
    """resolvable rows only: expected in top_k_rooms[:3]."""
    resolvable = [r for r in rows if not _is_adversarial(r)]
    if not resolvable:
        return None
    hits = 0
    for row in resolvable:
        ranking = row.get("top_k_rooms") or []
        hits += int(row.get("expected") in list(ranking)[:3])
    return hits / len(resolvable)


def oog_rate(rows: Sequence[Row]) -> Optional[float]:
    if not rows:
        return None
    return sum(1 for r in rows if r.get("out_of_graph")) / len(rows)


def malformed_rate(rows: Sequence[Row]) -> Optional[float]:
    """Free-form rows only: parse failures before any retry."""
    free_rows = [r for r in rows if r.get("mode") == "llm_free"]
    if not free_rows:
        return None
    return sum(1 for r in free_rows if r.get("malformed")) / len(free_rows)


def abstain_precision(rows: Sequence[Row]) -> Optional[float]:
    """Of rows the system abstained on, the fraction that were actually adversarial."""
    abstained = [r for r in rows if _abstained(r)]
    if not abstained:
        return None
    return sum(1 for r in abstained if _is_adversarial(r)) / len(abstained)


def abstain_recall(rows: Sequence[Row]) -> Optional[float]:
    """Of the adversarial rows, the fraction correctly abstained (== top1 on adversarial)."""
    adversarial = [r for r in rows if _is_adversarial(r)]
    if not adversarial:
        return None
    return sum(1 for r in adversarial if _abstained(r)) / len(adversarial)


def false_accept_rate(rows: Sequence[Row]) -> Optional[float]:
    """Adversarial rows answered with a room instead of abstaining."""
    adversarial = [r for r in rows if _is_adversarial(r)]
    if not adversarial:
        return None
    return sum(1 for r in adversarial if not _abstained(r)) / len(adversarial)


def false_abstain_rate(rows: Sequence[Row]) -> Optional[float]:
    """Resolvable rows the system abstained on instead of answering."""
    resolvable = [r for r in rows if not _is_adversarial(r)]
    if not resolvable:
        return None
    return sum(1 for r in resolvable if _abstained(r)) / len(resolvable)


def latency_percentiles(rows: Sequence[Row], exclude_cold: bool = True) -> Dict[str, Optional[float]]:
    """p50/p90 latency in ms. Excludes rows flagged ``cold`` (first call after a prefix
    rebuild) by default, per section 13's two-column rule and the brief's cold/warm split."""
    values = [
        float(r["latency_ms"])
        for r in rows
        if "latency_ms" in r and not (exclude_cold and r.get("cold"))
    ]
    if not values:
        return {"p50_ms": None, "p90_ms": None}
    values.sort()
    return {"p50_ms": _percentile(values, 0.50), "p90_ms": _percentile(values, 0.90)}


def _percentile(sorted_values: List[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = q * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def fast_path_hit_rate(rows: Sequence[Row]) -> Optional[float]:
    if not rows:
        return None
    return sum(1 for r in rows if r.get("mode") == "fast_path") / len(rows)


def per_category_top1(rows: Sequence[Row]) -> Dict[str, Optional[float]]:
    categories = sorted({r.get("category") for r in rows if r.get("category") is not None})
    return {cat: top1([r for r in rows if r.get("category") == cat]) for cat in categories}


def summarize(rows: Sequence[Row]) -> Dict[str, object]:
    """All section-5 metrics for one condition/baseline in one dict, ready to become a
    ``summary.csv`` row."""
    latency = latency_percentiles(rows)
    return {
        "n": len(rows),
        "top1": top1(rows),
        "top3": top3(rows),
        "oog_rate": oog_rate(rows),
        "malformed_rate": malformed_rate(rows),
        "abstain_precision": abstain_precision(rows),
        "abstain_recall": abstain_recall(rows),
        "false_accept_rate": false_accept_rate(rows),
        "false_abstain_rate": false_abstain_rate(rows),
        "p50_ms": latency["p50_ms"],
        "p90_ms": latency["p90_ms"],
        "fast_path_hit_rate": fast_path_hit_rate(rows),
        "per_category_top1": per_category_top1(rows),
    }
