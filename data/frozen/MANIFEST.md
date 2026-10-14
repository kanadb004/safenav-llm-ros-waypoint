# data/frozen manifest (PLAN.md 11A.9)

Every table in `docs/results/RESULTS.md` cites a file here by name. `data/runs/` and
`data/bags/` stay gitignored; this directory is the tracked, traceable subset (about 2.5 MB).
Bags are too large to commit and are recorded by path, size and `metadata.yaml` sha256 instead.

## JSONL files

| file | sha256 | rows | producing commit | producing command |
|---|---|---|---|---|
| phase8_e2e150_loopback.jsonl | ba02861fe6ac2578b40a3a8b2e35f25138924fab768f3684e9f4034e0e1ebf39 | 150 | fee405c (Phase 8, PR #25) | `ros2 run semantic_waypoint_planner run_trials.py --suite e2e150 --out data/runs/e2e150_loopback.jsonl --grammar-on --gate-threshold 0.85` |
| phase8_e2e150_grammar_off.jsonl | de119d2bdfc0d1105ae060c5c8d0c6e1665f8f262293d62184632edb75b0e59e | 50 | fee405c (Phase 8, PR #25) | `ros2 run semantic_waypoint_planner run_trials.py --suite e2e150 --out data/runs/e2e150_grammar_off.jsonl --no-grammar-on --gate-threshold 0.85` |
| phase8_e2e150_gate_off.jsonl | bce738fbe71e64ac52cb953562cb55ed795455c8c2b9118fb8229ddeed6b0860 | 50 | fee405c (Phase 8, PR #25) | `ros2 run semantic_waypoint_planner run_trials.py --suite e2e150 --out data/runs/e2e150_gate_off.jsonl --grammar-on --gate-threshold 0.0` |
| e2e150_loopback_rescored.jsonl | 97f8c22e94d5b13a2e35e688ae068369655fe22d7bbae862548ac1a2dafa0136 | 150 | 5165f39 (8B) | `python3 ml/safenav_ml/rescore_e2e150.py --in data/runs/e2e150_loopback.jsonl --out data/runs/e2e150_loopback_rescored.jsonl`; rescores phase8_e2e150_loopback.jsonl against the 11A.1 relabel rule, no inference re-run |
| e2e150_gate_off_8b.jsonl | 6262372a21a031c842754401423b4dee229aca8b17702b6dc44bf0474d20794e | 150 | 08d780c (8B) | `ros2 run semantic_waypoint_planner run_trials.py --suite e2e150 --out data/runs/e2e150_gate_off_8b.jsonl --grammar-on --gate-threshold 0.0 --no-bag`, fresh stack, fresh host llama-server (phi3-mini, port 8080), nothing else on the GPU |
| e2e150_grammar_off_8b.jsonl | 4edd7180127d76e6c4ebe3597706ac194fd94f0704d82b77bcaf3ec15c52560a | 150 | 08d780c (8B) | `ros2 run semantic_waypoint_planner run_trials.py --suite e2e150 --out data/runs/e2e150_grammar_off_8b.jsonl --no-grammar-on --gate-threshold 0.85 --no-bag`, fresh stack, fresh host llama-server (phi3-mini, port 8080), nothing else on the GPU. First launch attempt stalled (lifecycle_manager_semantic_nav stuck configuring map_server); discarded and relaunched, see docs/reports/phase-8b-corrective.md |
| phase5a_full500.jsonl | 084ec607d704251608147527912b2026bb1c884d03cc666fb294161b62e50c42 | 500 | Phase 5A (pre-8B, unchanged) | `python3 ml/safenav_ml/run_phase5_benchmark.py` (http backend), see docs/reports/phase-5a-corrective.md |
| model_ablation_phi3-mini-4k-instruct.Q4_K_M.jsonl | e4404f98a70807143ca9ee44bc72620a876c609c94b150d70a31527c8008513d | 500 | fee405c (Phase 8, PR #25) | `python3 ml/safenav_ml/model_ablation.py --out-dir data/runs/model_ablation` |
| model_ablation_tinyllama-1.1b-chat-v1.0.Q4_K_M.jsonl | ec3a43108b118a51d6c59ce579cedb0b0c0faee5db03425b2f6637bd644e86dc | 500 | fee405c (Phase 8, PR #25) | same invocation as above |
| model_ablation_phi3.5-mini-instruct.Q4_K_M.jsonl | 7103bd01622bc3341787ac93d61c8cf15c0f49f99d492645bab5a305d92228d6 | 500 | fee405c (Phase 8, PR #25) | same invocation as above |
| calibration_session1_trials.jsonl | 53d0956b61fbe58375ee4da97fdd57da9e73d41e9bb3c26ac5257e7321d3d7d4 | 200 | Phase 7 (pre-8B, unchanged) | `python ml/safenav_ml/run_trials.py --session 1 --out data/runs/calibration/session1_trials.jsonl` |
| calibration_session2_trials.jsonl | ed5233b7d604e501a3583e975705d8ccf86f6e8014ca5fce12aab65f1b8c8fe6 | 100 | Phase 7 (pre-8B, unchanged) | `python ml/safenav_ml/run_trials.py --session 2 --out data/runs/calibration/session2_trials.jsonl --calibrator-path ros2_ws/src/semantic_waypoint_planner/config/calibrator.json` |

Corrected spatial labels: the frozen rule itself is `CORRECTED_SPATIAL_LABELS` in
`ros2_ws/src/semantic_waypoint_planner/scripts/run_trials.py` (commit 08d780c), tested in
`ros2_ws/src/semantic_waypoint_planner/test/python/test_run_trials_suite.py`; it is code, not a
data file, and is applied to produce `e2e150_loopback_rescored.jsonl` above.

Note: `calibration_session1_trials.jsonl` and `calibration_session2_trials.jsonl` were
collected with `calibrator_loaded=False` (their `calibrated_confidence` column is
`raw_confidence` passed through the identity fallback, not the deployed calibrator's output).
`ml/safenav_ml/offline_gate_comparison.py` reconstructs the deployed calibrator's output from
each row's own stored feature values; see docs/results/offline_gate_comparison.md.

| text_anchor_replay_500.jsonl | e4113f59acaee7f71ddfa1df5b5a6cb5a619523f1ea2a44f13494188f98bb034 | 500 | Phase 8C (PLAN.md 11B.3) | `python3 ml/safenav_ml/replay_text_anchor.py --out docs/results/text_anchor_replay.md`; replays phase5a_full500.jsonl x synthetic_500_v2.jsonl through the text anchor fix, no inference re-run |
| text_anchor_replay_session1.jsonl | 885ac11450ecf1f3dd5616e66171bfcc683b5947416e4403fc668a5128bd8464 | 200 | Phase 8C (PLAN.md 11B.3) | same invocation as above; replays calibration_session1_trials.jsonl |
| text_anchor_replay_session2.jsonl | a506e1212075a94afe852a77b98d19b4c82a6b57c73da4b396f491eb8d431d76 | 100 | Phase 8C (PLAN.md 11B.3) | same invocation as above; replays calibration_session2_trials.jsonl |

## Bags (uncommitted, too large; path/size/hash recorded here)

| path | size | metadata.yaml sha256 |
|---|---|---|
| data/bags/e2e150_production/ | 112 MB | cc4825de22200be4839e3df0677f5ba9ebad40e6c9a840fc3e4b3bea73baa385 |

The two 8B reruns (gate-off, grammar-off) used `--no-bag`, consistent with Phase 8's own D56
practice for the ablation suites: the wrong-room action rate comparison (11A.4) does not depend
on the bag, and a 112 MB bag per suite would roughly double this already multi-hour pass's
unattended time with no DoD item depending on it.
