# Phase 0 report: scaffolding, environment, downloads

Date: 2026-09-13. Issue #1.

## What was built

- Repository scaffolding: `CLAUDE.md` (session workflow, git and engineering conventions),
  `docs/PLAN.md` (master plan, Phases 0 to 10 with definitions of done, frozen interface
  contracts, latency policy, recorded deviations), `README.md`, `.gitignore`, `.dockerignore`,
  original documents moved to `docs/reference/` with an index.
- Docker image in two stages (`docker/Dockerfile`, `docker/build.sh`, `docker/docker-compose.yml`):
  - `safenav-llm:core`: `tiryoh/ros2-desktop-vnc:humble` (Ubuntu 22.04, ROS 2 Humble desktop,
    noVNC) plus Nav2 1.1.20, nav2_bringup, slam_toolbox, BehaviorTree.CPP v3 3.8.7, ros2_control,
    rosbridge_suite, rosbag2 with mcap, espeak-ng, Gazebo Fortress 6.18 and its dev libraries,
    TurtleBot4 description, msgs, navigation, node and viz packages, llama.cpp b10941 built as
    shared libraries with tools into `/opt/llama.cpp`, Python deps (numpy 1.26, scikit-learn 1.7.2,
    scipy 1.14, pandas, matplotlib, anthropic 1.5, llama-cpp-python 0.3.16 CPU build).
  - `safenav-llm:humble`: core plus the simulation overlay `/opt/sim_ws` built from
    `third_party/ros_src` (ros_gz, gz_ros2_control, create3_sim, turtlebot4_simulator, humble
    branches; commits in `third_party/ros_src/VERSIONS.txt`).
  - `docker/safenav_env.sh` sources ROS, the overlay and the project workspace in every shell;
    software GL is forced for the noVNC desktop.
- Models in `models/` (git ignored): Phi-3 mini 4k instruct Q4_K_M (2.39 GB, from
  `microsoft/Phi-3-mini-4k-instruct-gguf`), TinyLlama 1.1B chat Q4_K_M (0.67 GB, `TheBloke`),
  Phi-3.5 mini instruct Q4_K_M (2.39 GB, `bartowski`).
- Host env `tf_env` (conda, Python 3.11) extended with llama-cpp-python 0.3.16 (Metal), anthropic,
  pytest, pytest-timeout, rapidfuzz, Levenshtein, pydantic, jsonschema, tqdm, pyyaml, pandas.
  `ml/requirements-host.txt` records the additions; `ml/safenav_ml/smoke_test.py` is the check.
- Disk: three unrelated Oracle Docker images removed with the user's permission (about 14 GB).

## Verification

Host smoke test (`ml/safenav_ml/smoke_test.py`, Metal, while the Docker build was hogging the
CPU, so latencies are pessimistic):

```
loaded phi3-mini-4k-instruct.Q4_K_M.gguf in 2.1s
'go to the kitchen'                -> {"room": "kitchen", "confidence": 0.98}        (2193 ms)
'somewhere I can charge the robot' -> {"room": "charging_dock", "confidence": 1.00}  (4533 ms)
'go to the cafeteria'              -> {"room": "kitchen", "confidence": 0.85}        (3679 ms)
```

The third line is a live example of failure type 2 from the architectural analysis (valid world
misinterpretation with high raw confidence), which the calibration gate of Phase 7 must catch.
TinyLlama and Phi-3.5 mini load and produce grammar valid JSON as well.

Core image checks (`docker run --rm --entrypoint bash safenav-llm:core -lc ...`):

```
ros2 pkg list: nav2_bt_navigator nav2_bringup behaviortree_cpp_v3 slam_toolbox turtlebot4_navigation rosbridge_server   (6 of 6)
llama-cli --version: built with GNU 11.4.0 for Linux aarch64
python3: llama_cpp 0.3.16, sklearn 1.7.2, anthropic 1.5.0, numpy 1.26.4
ign gazebo --version: Gazebo Sim, version 6.18.0
nproc 8, memory 7 GB (Docker Desktop allocation)
```

Full image checks (`docker compose up -d` then `exec dev bash -lc ...`):

```
ros2 pkg list: nav2_bt_navigator turtlebot4_ignition_bringup (2 of 2); overlay packages present:
  gz_ros2_control irobot_create_ignition_{bringup,plugins,sim,toolbox} ros_gz_sim
  turtlebot4_ignition_{bringup,gui_plugins,toolbox}
python3: llama_cpp 0.3.16, sklearn 1.7.2, scipy 1.14.1; /ws/models has the three GGUF files
CPU smoke test in the container: kitchen 14759 ms, charging_dock 9713 ms, cafeteria->kitchen 9073 ms
llama-bench in the container: pp64 7.21 tok/s, tg16 3.31 tok/s (8 threads)
host Metal: about 64 prompt tokens in 1136 ms, 16 generated tokens in 1558 ms
```

The container is 5 to 10 times slower than the Jetson target; PLAN section 13 records the
resulting latency policy (sim timeouts of 20 s, Metal proxy for the p90 gate).

## Deviations and decisions

- D1 (updated): Humble plus Gazebo Fortress plus TurtleBot4 was chosen over the specification's
  Harmonic because the official TurtleBot4 simulator pairs Humble with Fortress. On arm64 there are
  no Humble binaries for `turtlebot4_simulator`, `ros_gz_sim`, or `gazebo_ros_pkgs`, so the
  simulator stack is compiled from vendored sources inside the image.
- D2: dataset generation will use the Anthropic API instead of GPT-4 (user decision).
- D8: Phi-3.5 mini ablation model at Q4_K_M instead of Q8 (disk budget, user decision).
- Docker Desktop has 8 GB memory. Gazebo plus Nav2 plus a 2.4 GB model may not fit; the user
  should raise it to 12 GB before Phase 2.

## Build notes

- Ubuntu 22.04 pip (22.0) cannot build llama-cpp-python 0.3.16 (old `packaging`); the image
  upgrades pip, packaging and setuptools first.
- `ros_gz_bridge` compiles generated factory files that take about 2 GB of RAM per compiler
  process. With 4 parallel packages and `-j8` the 8 GB Docker VM ran out of memory; the overlay is
  built with `-j2` for the bridge, then `-j4` with two parallel packages for the rest.
- The base image entrypoint starts a MATE desktop with noVNC and ignores the command; use
  `docker compose up -d` plus `exec`, or `--entrypoint bash` for one off commands.

## Open risks for Phase 1 and 2

- Gazebo Fortress rendering in the container is software GL; the GPU lidar of the TurtleBot4 may
  be slow. The loopback simulator in Phase 2 is the fallback for batch runs.
- CPU inference latency in the container is not the deployment number (see PLAN section 13).
