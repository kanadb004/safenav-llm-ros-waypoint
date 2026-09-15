"""Root conftest so host pytest runs (``pytest ml/tests
ros2_ws/src/semantic_waypoint_planner/test/python``) can import the ROS free
``semantic_waypoint_planner`` package without it being pip installed. Inside the container,
``colcon test`` already sets PYTHONPATH, so this is a no-op there.
"""

import os
import sys

_PKG_SRC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ros2_ws", "src", "semantic_waypoint_planner"
)
if _PKG_SRC not in sys.path:
    sys.path.insert(0, _PKG_SRC)
