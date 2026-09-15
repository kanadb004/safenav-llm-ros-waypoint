import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safenav_ml.subsample import build_subsample  # noqa: E402


def _toy_rows():
    rows = []
    categories = ["direct", "alias", "spatial", "adversarial"]
    for cat in categories:
        for i in range(20):
            rows.append({"id": f"{cat}_{i}", "category": cat, "command": f"cmd {cat} {i}"})
    return rows


def test_subsample_has_n_per_category():
    rows = _toy_rows()
    sub = build_subsample(rows, n_per_category=8, seed=42)
    assert len(sub) == 32
    counts = {}
    for r in sub:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    assert all(c == 8 for c in counts.values())


def test_subsample_deterministic():
    rows = _toy_rows()
    sub1 = build_subsample(rows, n_per_category=8, seed=42)
    sub2 = build_subsample(rows, n_per_category=8, seed=42)
    assert [r["id"] for r in sub1] == [r["id"] for r in sub2]


def test_subsample_different_seed_can_differ():
    rows = _toy_rows()
    sub1 = build_subsample(rows, n_per_category=8, seed=42)
    sub2 = build_subsample(rows, n_per_category=8, seed=7)
    assert [r["id"] for r in sub1] != [r["id"] for r in sub2]
