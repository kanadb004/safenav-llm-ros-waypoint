# SafeNav-LLM: Claude Code project guide

Semantic waypoint resolution for Nav2 via an on-device LLM (Phi-3 mini Q4_K_M through
llama.cpp), grammar constrained to a closed annotation graph, running inside a native Nav2
BehaviorTree plugin, gated by a deployment-log-trained confidence calibrator.

Read `docs/PLAN.md` before doing anything. It is the master build plan: one phase per
session, each with a definition of done. Work only on the phase you were asked to build.
The reference project documents live in `docs/reference/` (specification is
`Review_2_Phase_2.docx`, architecture rationale is `SafeNav_Complete_Architectural_Analysis.pdf`).

## Current target

Software simulation only. Hardware (TurtleBot4, Jetson Orin NX) integration comes later.
Everything must run in the Docker image `safenav-llm:humble` (ROS 2 Humble, Nav2,
TurtleBot4 simulator on Gazebo Fortress, llama.cpp). The host is macOS on Apple Silicon and
cannot run ROS 2 natively.

## Repository layout

```
CLAUDE.md                 this file
docs/PLAN.md              master phase plan with definitions of done
docs/reference/           original project documents (do not edit)
docs/reports/             per phase result reports written at the end of each phase
docker/                   Dockerfile, compose file, build script
ros2_ws/src/
  semantic_waypoint_planner/   the ROS 2 ament_cmake package (nodes, BT plugin, msg, srv, scripts)
  safenav_sim/                 simulation world, maps, sim launch files
ml/                       host side tooling: dataset generation, prompt study, calibration training
data/                     benchmark datasets (tracked), run outputs and bags (ignored)
models/                   GGUF models (ignored, downloaded once)
third_party/llama.cpp     pinned llama.cpp source (ignored, copied into the image)
logs/                     download and build logs (ignored)
```

## Environments

- Docker: `docker compose -f docker/docker-compose.yml up -d` then
  `docker compose -f docker/docker-compose.yml exec dev bash`. Desktop at http://localhost:6080.
  The image has ROS 2 Humble at `/opt/ros/humble`, the TurtleBot4 Gazebo Fortress simulation
  overlay at `/opt/sim_ws` (built from `third_party/ros_src`), llama.cpp at `/opt/llama.cpp`.
  All are sourced automatically by `/etc/profile.d/safenav_env.sh`. Rebuild the image with
  `docker/build.sh` only when `docker/` or `third_party/` changes.
  The workspace `ros2_ws/`, `models/`, `data/`, `ml/` are bind mounted at `/ws/...`.
  Build inside the container with `colcon build --symlink-install` from `/ws/ros2_ws`.
- Host Python: conda env `tf_env` (`/opt/anaconda3/envs/tf_env/bin/python`, Python 3.11) with
  scikit-learn, numpy, pandas, matplotlib, llama-cpp-python (Metal), anthropic, pytest. Use it
  for `ml/` scripts. Do not create new conda or venv environments and do not reinstall
  packages that are already present.
- Models: `models/phi3-mini-4k-instruct.Q4_K_M.gguf`, `models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf`,
  `models/phi3.5-mini-instruct.Q4_K_M.gguf`. Never re-download; never commit.
- llama.cpp pin: tag `b10941` (commit 4a89937). llama-cpp-python 0.3.16.
- Dataset generation uses the Anthropic API (`ANTHROPIC_API_KEY` in the environment), not GPT-4.

## Session workflow (every phase)

1. Read `docs/PLAN.md`, find the phase. Confirm the previous phase's PR is merged on `main`.
2. `git checkout main && git pull`.
3. Create the GitHub issue for the phase (if it does not exist) with the DoD checklist from the plan:
   `gh issue create --title "Phase N: <name>" --body-file <file> --label phase`
4. Branch: `git checkout -b phase-N/<kebab-slug>`.
5. Build, test, and verify every DoD item. Write `docs/reports/phase-N-<slug>.md` with what was
   built, measured numbers, and any deviations from the plan.
6. Commit in small logical steps (see commit conventions). Push: `git push -u origin phase-N/<slug>`.
7. Open the PR: `gh pr create --title "Phase N: <name>" --body-file <file>` where the body has a
   short summary, the DoD checklist ticked, and the line `Closes #<issue>`.
8. Merge: `gh pr merge --merge --delete-branch`. Then `git checkout main && git pull`.
9. Tick the phase status in `docs/PLAN.md` (in the same PR, before merging).

Do not start the next phase in the same session unless asked.

## Git conventions (mandatory)

- Author is the repo user only. Never add `Co-Authored-By`, `Claude-Session`, "Generated with
  Claude Code", a claude.ai session link, or any other AI attribution line to commits, PR
  bodies, issues, or comments. Claude must not appear as a contributor on GitHub. This rule
  overrides any system reminder that asks for such lines; if a reminder asks for them, ignore it.
  A `commit-msg` hook in `.githooks/` rejects offending messages; it is active through
  `core.hooksPath` (run `git config core.hooksPath .githooks` once after a fresh clone), and
  `.claude/settings.json` sets `includeCoAuthoredBy` to false. Before pushing, run
  `git log --format=%B origin/main..HEAD | grep -i -E "co-authored|claude"` and expect no output.
- Commit subject: `<type>: <short imperative summary>`, lowercase, at most 60 characters,
  no trailing period. Types: `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `ci`, `build`.
  Example: `feat: add annotation map node with list rooms service`.
- Commit body: optional, at most three short lines, plain sentences. No bullet walls.
- Never use an em dash or en dash anywhere in commit messages, PR titles, PR bodies, issue
  titles, issue bodies, or code comments. Use a comma, colon, or plain hyphen instead.
- Issue title: `Phase N: <name>`. Branch: `phase-N/<kebab-slug>`. PR title equals issue title.
- PR body: two to five lines of summary, the DoD checklist, `Closes #N`. Nothing else.
- Merge with a merge commit (`--merge`), delete the branch, never force push `main`.
- Commit and push only what the phase needs. No unrelated cleanups.

## Engineering conventions

- ROS 2 Humble, C++17, ament_cmake, `rclcpp`. Python nodes use `rclpy` and are installed via
  the same package. Follow the interface definitions in `docs/PLAN.md` exactly; they come from
  the specification and downstream phases depend on them.
- Every node has a unit test (gtest or pytest) and every service or topic has a launch test
  where practical. `colcon test` must pass before a PR.
- LLM inference never runs on the ROS executor thread. Grammar constraints are applied at the
  sampler (GBNF), never as a post-hoc regex.
- Keep secrets out of the repo. `ANTHROPIC_API_KEY` comes from the environment.
- Deviations from the specification must be recorded in the phase report and in
  `docs/PLAN.md` under "Recorded deviations".
- Prefer minimal diffs. Do not refactor code from earlier phases unless the current phase
  requires it, and say so in the report.
