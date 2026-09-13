# SafeNav-LLM

Semantic waypoint resolution for ROS 2 Nav2: an on-device language model (Phi-3 mini Q4_K_M via
llama.cpp) resolves natural language commands such as "go to the charging dock near the fire
exit" into a named location from a closed, human curated annotation graph. The output is
constrained at the token sampler with a GBNF grammar, the resolution runs inside a native Nav2
BehaviorTree plugin, and a calibrated confidence gate decides between navigating and asking the
operator to rephrase.

Current target: software simulation (TurtleBot4 in Gazebo Fortress, ROS 2 Humble) inside Docker.
Hardware deployment on a TurtleBot4 with a Jetson Orin NX is a later phase.

## Documents

- `docs/PLAN.md`: the master build plan, phase by phase, with definitions of done.
- `docs/reference/`: the project specification, architectural analysis, and review reports.
- `docs/reports/`: per phase build reports with measured numbers.
- `CLAUDE.md`: conventions for Claude Code sessions (workflow, git rules, environments).

## Quick start

```
docker/build.sh                                   # one time, builds safenav-llm:humble
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml exec dev bash
colcon build --symlink-install                    # inside the container, in /ws/ros2_ws
```

Desktop (RViz2, Gazebo GUI) at http://localhost:6080. Models live in `models/` (see
`docs/PLAN.md` Phase 0). The package tour, launch commands and results are filled in as the
phases are completed.
