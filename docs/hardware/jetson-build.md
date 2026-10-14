# Jetson Orin NX build recipe

Written in Phase 9 (PLAN.md section 15), reviewed line by line against `docker/Dockerfile.jetson`
without a Jetson present. Not executed. Phase 10 runs this on the real device and records every
place it had to change in `docs/reports/phase-10-*.md`.

## Prerequisites on the device

1. Flash the Orin NX with **JetPack 6.x** (L4T r36.x, Ubuntu 22.04 Jammy), not JetPack 5
   (Ubuntu 20.04). See failure mode 1 below for why this choice is load bearing.
2. Install `nvidia-container-toolkit` so Docker containers get GPU and CUDA device access
   (`docker run --runtime nvidia` or the `nvidia` runtime set as default in
   `/etc/docker/daemon.json`). JetPack images ship this by default; confirm with
   `docker info | grep -i runtime`.
3. At least 40 GB free on the root filesystem (or an NVMe mounted and used as the Docker data
   root): the base `dustynv/ros:humble-ros-base-l4t-r36.2.0` image is 6 to 8 GB, ROS 2
   Humble plus Nav2 and TurtleBot4 packages add roughly 2 GB, the llama.cpp CUDA build adds
   under 1 GB, and Docker's layer cache during the build roughly doubles the peak. Devkit eMMC
   or a small SD card will not have this much free; plan for an NVMe boot or data drive.

## Build

```bash
docker build -f docker/Dockerfile.jetson -t safenav-llm:jetson .
```

Expected build time on an Orin NX (8 CPU cores, this is a build-time estimate from the llama.cpp
project's published Jetson benchmarks and the dev image's measured arm64 CPU build time for the
same llama.cpp tag under QEMU emulation on the Apple Silicon host, not a direct Orin
measurement): roughly 25 to 40 minutes, dominated by the `colcon build` of Nav2's dependency
tree pulled in by `rosdep install` (apt, a few minutes) and the llama.cpp CUDA compile
(`ggml-cuda` has one translation unit per quantization kernel; `-j2` keeps peak memory per
compiler process under the Orin NX 8 GB variant's limit at some cost to wall time). Phase 10
replaces this estimate with a measured number.

## Known failure modes

1. **JetPack version mismatch (Ubuntu 20.04 vs 22.04).** JetPack 5.x Jetsons run an Ubuntu
   20.04 (Focal) rootfs. ROS 2 Humble has no apt repo for Focal arm64; `dustynv`'s JetPack 5
   images work around this by rebuilding ROS from source into a custom apt mirror, which lags
   upstream Humble and has had Nav2/BehaviorTree.CPP version skew in the past. This repository
   targets JetPack 6 (L4T r36.x, Ubuntu 22.04 Jammy) specifically so Humble installs from its
   own official arm64 Jammy apt repo, same as any other arm64 Ubuntu 22.04 host, with the dev
   image's own well understood package set. Remedy if the device in hand is JetPack 5: either
   reflash to JetPack 6 (Orin NX supports it), or switch the base image to a `dustynv`
   JetPack 5 tag and re-verify every apt package version pin in this Dockerfile against that
   mirror's catalog, since the package set is not guaranteed to match.
2. **CUDA architecture auto-detection picks the wrong (or no) SM.** `cmake --build` for
   llama.cpp's CUDA backend needs `CMAKE_CUDA_ARCHITECTURES` set at configure time. Orin NX is
   compute capability 8.7 (`sm_87`). Leaving this to `native` or CMake's own detection logic
   silently fails or targets the wrong architecture when no GPU is visible to the Docker build
   context (the default on most Jetson Docker setups, since `docker build` does not take
   `--runtime nvidia`), producing a `llama-server` binary that either fails to load its CUDA
   kernels at runtime or silently falls back to CPU. Remedy: this Dockerfile already pins
   `-DCMAKE_CUDA_ARCHITECTURES=87` explicitly; if NVIDIA retires `sm_87` support in a future
   CUDA toolkit bundled with a newer JetPack, re-check Orin NX's compute capability against
   that toolkit's supported list before changing the flag.
3. **Out of memory during the build, not at `colcon build` but at `ninja` link time for
   `ggml-cuda`.** Each CUDA compilation unit here can need 1 to 2 GB of host RAM; on the 8 GB
   Orin NX variant, the default `nproc`-wide parallelism (the dev image uses `-j"$(nproc)"`
   for the CPU build) can OOM-kill the build partway through with no clear error beyond
   `ninja: build stopped: subcommand failed`. Remedy: this Dockerfile already caps the llama.cpp
   build at `-j2`; if the build still OOMs on a particular unit (16 GB variant should not need
   this), either lower further or add a swap file before building, never remove `-j2` in favor
   of `-j"$(nproc)"` without first confirming the device's RAM size.

## What this recipe does not cover

The TurtleBot4 hardware bringup stack itself (iRobot Create 3 firmware, the TurtleBot4's own
Raspberry Pi companion computer that runs the Create 3 driver node) is out of scope for this
Dockerfile, which only builds what runs on the Orin NX. See `cannot-verify.md` for what cannot
be checked before the robot is in hand regardless.
