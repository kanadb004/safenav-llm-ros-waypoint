# Sourced by every shell in the safenav-llm image.
source /opt/ros/humble/setup.bash
[ -f /opt/sim_ws/install/setup.bash ] && source /opt/sim_ws/install/setup.bash
[ -f /ws/ros2_ws/install/setup.bash ] && source /ws/ros2_ws/install/setup.bash
export IGNITION_VERSION=fortress
export GZ_VERSION=fortress
export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}
export SAFENAV_MODELS_DIR=${SAFENAV_MODELS_DIR:-/ws/models}
export LIBGL_ALWAYS_SOFTWARE=1
export QT_X11_NO_MITSHM=1
