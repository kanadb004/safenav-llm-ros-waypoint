# Phase 7: confidence calibration pipeline

## 1. What this phase built

- `ml/safenav_ml/gen_personas.py`: generates the two simulated deployment logs via the Mistral
  REST API (`ministral-14b-latest`, temperature 1.0, no SDK). Five personas (admin staff x2,
  non-robotics PhD students x2, one undergraduate from another department), each producing 40
  session 1 (training) and 20 session 2 (evaluation) commands, balanced across the benchmark's
  seven resolvable categories (direct, alias, spatial, functional, negation, abbreviation,
  multi_hop; no adversarial category here, since every row is labeled with a real intended
  location per the plan). One combined Mistral call per persona/category pool is split into the
  two sessions, which makes session 1/session 2 disjointness structural rather than checked
  after the fact; it is still verified by normalized string equality plus a fuzzy (ratio >= 90)
  threshold against each other and against `data/benchmark/synthetic_500.jsonl`. Output:
  `data/calibration/session1_sim.jsonl` (200 rows), `data/calibration/session2_sim.jsonl` (100
  rows), both committed.
- `ml/safenav_ml/run_trials.py`: replays a session file through `ResolverCore` directly
  (`backend=http` against a host `llama-server`, production configuration: `fewshot_count=0`,
  `temperature=0.3`, grammar on), recording the section 12.9 fields that apply plus the five
  section 12.8 features per row. See section 4 for why this bypasses the full `/semantic_goal`
  ROS graph rather than driving it, which is a deviation from the plan's literal wording.
- `ml/safenav_ml/metrics.py`: added `ece`, `brier_score`, `reliability_bins`,
  `false_pass_rate`, `false_rejection_rate` as pure functions over `(probability, label)` pairs,
  unit tested in `ml/tests/test_metrics.py` (`test_ece_*`, `test_brier_score_known_value`,
  `test_false_pass_rate_*`, `test_false_rejection_rate_*`, `test_reliability_bins_*`).
- `ml/safenav_ml/train_calibrator.py`: `StandardScaler` + `LogisticRegression` on the five
  section 12.8 features, 5-fold leave-one-persona-out cross-validation on session 1, reporting
  CV ECE, Brier, and an isotonic-regression variant (comparison only, not deployed). Picks the
  threshold as the lowest value whose out-of-fold false pass rate is <= 5%. Writes
  `config/calibrator.json`, `docs/results/calibration_session1.png` (reliability diagram over
  the session 1 out-of-fold predictions), `docs/results/calibration_metrics.json` (the full
  metrics table), and `test/fixtures/calibrator_parity_vectors.json` (20 feature vectors plus
  the trained model's own predicted probability, for the parity test). Also evaluates on session
  2 with the calibrator loaded, and computes the gated end-to-end accuracy on the 500 benchmark
  by reconstructing the five features from a cached Phase 5A run
  (`data/runs/phase5a_full500.jsonl`) and applying the new calibrator and threshold, joined
  against `data/benchmark/synthetic_500_v2.jsonl`'s corrected labels, without re-running the LLM.
- `test/python/test_calibrator_parity.py`: asserts `Calibrator.calibrate()` agrees with the
  sklearn model's own `predict_proba` within 1e-6 on all 20 exported vectors. This is the D27
  Python-versus-sklearn replacement for the v1 C++-versus-sklearn parity test, since the
  calibrator stayed in Python.
- `config/calibrator.json`: trained artifact, committed (section 12.8 schema, `threshold:
  0.85`).
- Wired the resolver node's `calibrator_path` parameter to default to
  `<share>/config/calibrator.json` (`scripts/llm_resolver.py`) so the calibrator loads
  automatically once the package is built, with no extra launch argument.
- Raised the default `confidence_threshold` from 0.72 to 0.85 (the trained value) everywhere a
  caller actually sets it: `scripts/say.py`'s CLI default, `SemanticNavigateToPose`'s BT port
  default (`bt_semantic_plugin.hpp`, `.cpp`'s `getInput` fallback), and
  `plugin_description.xml`'s documentation. `msg/SemanticGoal.msg`'s own comment (section 12.1,
  frozen) is left at 0.72 verbatim: it documents the message field's informal convention, not an
  enforced default (ROS messages have none), and editing a comment inside a frozen interface
  file was judged an unnecessary risk for no behavioural gain. `config/planner_params.yaml`
  gained a comment pointing an operator at `calibrator.json`'s own `threshold` field as the
  source of truth, rather than a second, possibly-drifting copy of the number.
- Updated `test/test_semantic_nav_launch.py`'s default and assertion from 0.72 to 0.85 to match.

## 2. Verification

```
PYTHONPATH=ros2_ws/src/semantic_waypoint_planner python3 -m pytest \
  ros2_ws/src/semantic_waypoint_planner/test/python/ -q
# 103 passed

python3 -m pytest ml/tests/ -q
# 35 passed

docker compose -f docker/docker-compose.yml exec dev bash -lc \
  "cd /ws/ros2_ws && colcon build --symlink-install --packages-select semantic_waypoint_planner"
# Finished <<< semantic_waypoint_planner

docker compose -f docker/docker-compose.yml exec dev bash -lc \
  "cd /ws/ros2_ws && colcon test --packages-select semantic_waypoint_planner --event-handlers console_direct+"
# 100% tests passed, 5 tests (gtest, 3 launch tests, 1 pytest wrapper)
```

`semantic_cli` manual check (annotation node plus the Python resolver, `backend=http` against
the host `llama-server`, default `calibrator_path`):

```
$ ros2 run semantic_waypoint_planner semantic_cli "go to the kitchen" --timeout 60
{
  "matched_room_name": "kitchen",
  "raw_confidence": 0.9900000095367432,
  "calibrated_confidence": 0.9947658777236938,
  "resolver_mode": "fast_path",
  "calibrator_loaded": true,
  ...
}
```

`calibrated_confidence != raw_confidence` and `calibrator_loaded: true`, as required. (Fast path
responses also go through the calibrator; its raw_confidence of 0.99 happens to calibrate
upward here rather than downward, which the reliability diagram explains: the model is
underconfident, not overconfident, in the region near 0.99.)

## 3. Measured numbers

| Metric | Value | Target | Result |
|--------|-------|--------|--------|
| Session 1 rows | 200 (5 personas x 40) | 200 | met |
| Session 2 rows | 100 (5 personas x 20) | 100 | met |
| Session 1/2 overlap | 0 | disjoint | met |
| Session 1/2 vs. 500 benchmark overlap | 0 | disjoint | met |
| Session 1 raw resolver accuracy (resolved == intended) | 0.705 (141/200) | n/a | measured |
| CV ECE (session 1, out-of-fold, logistic) | 0.0698 | <= 0.10 | met |
| CV ECE (session 1, out-of-fold, isotonic, comparison only) | 0.1076 | n/a | reported |
| CV Brier (session 1, logistic) | 0.1433 | n/a | reported |
| Raw-confidence ECE (session 1, uncalibrated) | 0.2114 | n/a | reported |
| Session 2 raw-confidence ECE | 0.2030 | n/a | reported |
| Session 2 calibrated ECE | 0.0730 | <= 0.08 | met |
| Session 2 false pass rate | 0.0426 | <= 5% | met |
| Session 2 false rejection rate | 0.3662 | <= 15% | **missed** |
| Gated end-to-end accuracy, 500 benchmark (corrected labels) | 0.72 | >= 0.85 | **missed** |
| Threshold written to `calibrator.json` | 0.85 | n/a | deployed |

Gated per-category accuracy (500 benchmark, corrected labels, gate on):

| category | gated top-1 |
|----------|-------------|
| direct | 0.969 |
| alias | 0.938 |
| multi_hop | 0.815 |
| abbreviation | 0.877 |
| adversarial | 0.889 |
| spatial | 0.708 |
| functional | 0.323 |
| negation | 0.292 |

## 4. Deviations

- **D49: `run_trials.py` calls `ResolverCore` directly rather than driving the full
  `/semantic_goal` -> Nav2 ROS graph.** The plan's section 10 says the script "replays a command
  file through `/semantic_goal` ... in loopback mode." This phase instead follows the Phase 5
  precedent (`run_phase5_benchmark.py`, D28): a host-side script against `backend=http`, which
  is what fits a 300-row replay into a morning. The plan's own text says the navigation outcome
  in loopback is deterministic given the resolved room, and that the calibration label is simply
  `resolved == intended`; driving the full BT plugin and Nav2 stack for 300 commands would add
  substantial runtime and infrastructure without changing that label. The richer `/semantic_goal`
  -driven suite (bags, `nav_result`, pose fields) is still needed for Phase 8's `e2e150` suite
  and is left to that phase, which will extend this script rather than replace it.
- **D50: trial outputs live under `data/runs/calibration/`, not `data/calibration/`.** The plan's
  v1 text names `data/calibration/session1_trials.jsonl`. This repository's established
  convention (section 2 of `PLAN.md`) is that `data/runs/` holds regenerable run output and is
  gitignored, while `data/calibration/` holds committed source data (the two `*_sim.jsonl`
  files). The trial JSONL is reproducible from the committed session files plus
  `run_trials.py`, so it follows the `data/runs/` convention instead.
- **D51: the system-wide default `confidence_threshold` is raised from 0.72 to 0.85** (the
  trained value) at every call site except the frozen `SemanticGoal.msg` comment; see section 1.
- **D52: the gated end-to-end accuracy (0.72) and the session 2 false rejection rate (0.3662)
  both miss their targets (>= 0.85 and <= 15%), and this was not corrected by retuning on
  session 2, per the plan's explicit instruction.** Root cause: the grammar-constrained model's
  self-reported `raw_confidence` is only weakly discriminative between correct and incorrect
  resolutions. In session 1, correct resolutions average 0.925 raw confidence and incorrect ones
  average 0.896, both clustered inside a narrow 0.75-0.99 band (this echoes the Phase 3/4
  finding that the model's own confidence output carries little signal). Because the five
  features cannot separate the two classes much better than that, hitting the specification's
  <= 5% false pass safety bound forces the logistic model's decision threshold up to 0.85 on the
  calibrated scale, and that same high bar then rejects 36.6% of resolutions that were actually
  correct. The two misses are the same underlying cause, not independent problems: a
  wide-margin safety gate and a tight accuracy gate are in tension whenever the underlying
  confidence signal is this weakly separated, and no amount of retuning the threshold on session
  2 would resolve that tension, it would only move the loss from one metric to the other. This
  is reported as measured, left as an open risk into Phase 8, and is the headline number the
  specification's accuracy requirement should be read against.

## 5. Open risks for Phase 8

- The gated accuracy gap (0.72 vs. 0.85) is a resolver-confidence-signal problem, not a
  calibration-fitting problem; Phase 8's model ablation (Phi-3 mini vs. TinyLlama vs. Phi-3.5
  mini) is the next place this could plausibly improve, since it changes what confidence signal
  is available in the first place rather than how it is scaled.
  `functional` (0.323) and `negation` (0.292) gated accuracy are far below their raw per-category
  top-1 numbers from Phase 5A, meaning the gate disproportionately rejects commands in exactly
  the categories where the resolver is usually right; this is worth a per-category false
  rejection breakdown in Phase 8 rather than treating the aggregate 0.3662 as uniform.
- `data/runs/phase5a_full500.jsonl` is not committed (it lives in the gitignored `data/runs/`
  tree); the gated-500 recomputation in this phase depends on it existing locally. Phase 8
  should either commit a frozen copy of one full-500 resolver run or regenerate it explicitly
  as part of that phase's reproducibility story, since this phase's cheap feature-reconstruction
  trick depends on having one on disk.
