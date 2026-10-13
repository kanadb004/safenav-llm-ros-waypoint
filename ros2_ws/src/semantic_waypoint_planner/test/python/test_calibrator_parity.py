"""Phase 7 DoD: the Python ``Calibrator`` must agree with sklearn's own prediction within
1e-6 on vectors exported by ``train_calibrator.py`` (the D27 replacement for the v1 C++ versus
sklearn parity test, since the calibrator stayed in Python).

Needs ``config/calibrator.json`` and ``test/fixtures/calibrator_parity_vectors.json``, both
written by ``python ml/safenav_ml/train_calibrator.py``; skipped if either is absent (e.g. a
fresh checkout before Phase 7's training step has been run).
"""

import json
import os

import pytest

from semantic_waypoint_planner.resolver_core import Calibrator

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CALIBRATOR_PATH = os.path.join(PACKAGE_DIR, "config", "calibrator.json")
FIXTURES_PATH = os.path.join(PACKAGE_DIR, "test", "fixtures", "calibrator_parity_vectors.json")

pytestmark = pytest.mark.skipif(
    not (os.path.exists(CALIBRATOR_PATH) and os.path.exists(FIXTURES_PATH)),
    reason="config/calibrator.json or the parity fixture has not been generated yet",
)


def load_vectors():
    with open(FIXTURES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_calibrator_matches_sklearn_within_1e6():
    calibrator = Calibrator(CALIBRATOR_PATH)
    assert calibrator.loaded
    vectors = load_vectors()
    assert len(vectors) >= 20

    for vec in vectors:
        got = calibrator.calibrate(vec["features"][0], vec["features"])
        expected = vec["expected_probability"]
        assert abs(got - expected) < 1e-6, (got, expected, vec["features"])
