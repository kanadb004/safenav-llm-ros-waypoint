#!/bin/bash
# Builds safenav-llm:core (ROS 2 Humble, Nav2, llama.cpp, python deps) and then
# safenav-llm:humble (core plus the TurtleBot4 Gazebo Fortress simulation overlay).
# Run from anywhere. Extra args are passed to docker build (for example --no-cache).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
docker build --target core -t safenav-llm:core -f docker/Dockerfile "$@" .
docker build --target full -t safenav-llm:humble -f docker/Dockerfile "$@" .
