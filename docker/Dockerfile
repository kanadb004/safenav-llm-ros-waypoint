# SafeNav-LLM development and simulation image
# Base: Ubuntu 22.04 + ROS 2 Humble desktop + LXDE + noVNC (port 6080)
FROM tiryoh/ros2-desktop-vnc:humble AS core

ARG DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=humble
SHELL ["/bin/bash", "-lc"]

# OSRF apt repo for Gazebo (Ignition) Fortress, used by the TurtleBot4 simulation overlay
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg lsb-release ca-certificates \
 && curl -fsSL https://packages.osrfoundation.org/gazebo.gpg -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/gazebo-stable.list \
 && rm -rf /var/lib/apt/lists/*

# Build tooling, Nav2, Gazebo (Ignition) Fortress, ros2_control, TurtleBot4 runtime deps,
# SLAM, BT, bag, TTS. TurtleBot4 simulation itself is built from vendored sources below
# because ros-humble-turtlebot4-simulator and ros-humble-ros-gz-sim have no arm64 binaries.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build git pkg-config \
    python3-pip python3-colcon-common-extensions python3-rosdep python3-vcstool \
    nlohmann-json3-dev libcurl4-openssl-dev libgflags-dev \
    espeak-ng mesa-utils libgl1-mesa-dri \
    ignition-fortress \
    libignition-common4-dev libignition-gazebo6-dev libignition-gui6-dev \
    libignition-msgs8-dev libignition-plugin-dev libignition-transport11-dev \
    ros-humble-navigation2 \
    ros-humble-nav2-bringup \
    ros-humble-nav2-simple-commander \
    ros-humble-turtlebot4-description \
    ros-humble-turtlebot4-msgs \
    ros-humble-turtlebot4-navigation \
    ros-humble-turtlebot4-node \
    ros-humble-turtlebot4-viz \
    ros-humble-irobot-create-msgs \
    ros-humble-ros2-control \
    ros-humble-ros2-controllers \
    ros-humble-controller-manager \
    ros-humble-hardware-interface \
    ros-humble-joint-state-broadcaster \
    ros-humble-joint-state-publisher \
    ros-humble-rsl \
    ros-humble-actuator-msgs \
    ros-humble-control-msgs \
    ros-humble-gps-msgs \
    ros-humble-vision-msgs \
    ros-humble-xacro \
    ros-humble-sdformat-urdf \
    ros-humble-image-transport-plugins \
    ros-humble-slam-toolbox \
    ros-humble-behaviortree-cpp-v3 \
    ros-humble-pluginlib \
    ros-humble-rosbridge-suite \
    ros-humble-rosbag2 \
    ros-humble-rosbag2-storage-mcap \
    ros-humble-rmw-cyclonedds-cpp \
    ros-humble-ament-cmake-clang-format \
    ros-humble-ament-lint-auto \
    ros-humble-ament-lint-common \
    ros-humble-launch-testing \
    ros-humble-launch-testing-ros \
 && rm -rf /var/lib/apt/lists/*

# llama.cpp: shared libs + headers + CLI tools installed to /opt/llama.cpp
COPY third_party/llama.cpp /tmp/llama.cpp
RUN cmake -S /tmp/llama.cpp -B /tmp/llama.cpp/build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_SHARED_LIBS=ON \
      -DLLAMA_CURL=OFF \
      -DLLAMA_BUILD_TESTS=OFF \
      -DLLAMA_BUILD_EXAMPLES=OFF \
      -DLLAMA_BUILD_TOOLS=ON \
      -DLLAMA_BUILD_SERVER=ON \
      -DCMAKE_INSTALL_PREFIX=/opt/llama.cpp \
 && cmake --build /tmp/llama.cpp/build -j"$(nproc)" \
 && cmake --install /tmp/llama.cpp/build \
 && rm -rf /tmp/llama.cpp
ENV LD_LIBRARY_PATH=/opt/llama.cpp/lib:${LD_LIBRARY_PATH}
ENV PATH=/opt/llama.cpp/bin:${PATH}
ENV CMAKE_PREFIX_PATH=/opt/llama.cpp:${CMAKE_PREFIX_PATH}

# Python dependencies (llama-cpp-python builds against its bundled llama.cpp, CPU only)
COPY docker/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --upgrade "pip>=24" "packaging>=24" "setuptools>=70" wheel \
 && pip3 install --no-cache-dir -r /tmp/requirements.txt \
 && CMAKE_ARGS="-DGGML_NATIVE=ON" pip3 install --no-cache-dir llama-cpp-python==0.3.16 \
 && rm /tmp/requirements.txt

# Workspace and runtime defaults
RUN mkdir -p /ws/ros2_ws /ws/models
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV SAFENAV_MODELS_DIR=/ws/models
COPY docker/ros_entrypoint.sh /ros_entrypoint.sh
COPY docker/safenav_env.sh /etc/profile.d/safenav_env.sh
RUN chmod +x /ros_entrypoint.sh \
 && echo 'source /etc/profile.d/safenav_env.sh' >> /root/.bashrc \
 && echo 'source /etc/profile.d/safenav_env.sh' >> /etc/bash.bashrc
WORKDIR /ws/ros2_ws

# ---------------------------------------------------------------------------
FROM core AS full

# Simulation overlay built from vendored sources (see third_party/ros_src/VERSIONS.txt):
# ros_gz (humble), gz_ros2_control (humble), create3_sim (humble), turtlebot4_simulator (humble)
ENV IGNITION_VERSION=fortress
ENV GZ_VERSION=fortress
COPY third_party/ros_src /opt/sim_ws/src
RUN source /opt/ros/humble/setup.bash \
 && cd /opt/sim_ws \
 && colcon build --merge-install --cmake-args -DCMAKE_BUILD_TYPE=Release \
      --event-handlers console_direct+ --parallel-workers 4 \
 && rm -rf /opt/sim_ws/build /opt/sim_ws/log

