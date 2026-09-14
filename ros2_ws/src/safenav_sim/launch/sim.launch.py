"""Bring up Gazebo Fortress with the safenav_lab world and spawn a TurtleBot4 at the
reception dock.

Note: turtlebot4_ignition_bringup's own ignition.launch.py forwards a `world` name through
`ign_args` to ros_ign_gazebo's ign_gazebo.launch.py, but that shim in this image includes
ros_gz_sim's gz_sim.launch.py with no launch arguments at all, so `ign_args` never reaches
Gazebo (a leftover of the ignition -> gz rename). This launch file calls ros_gz_sim's
gz_sim.launch.py directly with an absolute path to our world file instead, and reuses
turtlebot4_ignition_bringup's turtlebot4_spawn.launch.py for the robot, dock, and bridges
which does not go through that broken chain.
"""

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node

ARGUMENTS = [
    DeclareLaunchArgument("gui", default_value="true", choices=["true", "false"],
                          description="Start the Gazebo client GUI"),
    DeclareLaunchArgument("model", default_value="lite", choices=["standard", "lite"],
                          description="TurtleBot4 model"),
    DeclareLaunchArgument("x", default_value="1.0", description="Robot spawn x"),
    DeclareLaunchArgument("y", default_value="6.0", description="Robot spawn y"),
    DeclareLaunchArgument("yaw", default_value="0.0", description="Robot spawn yaw"),
]


def generate_launch_description():
    pkg_safenav_sim = get_package_share_directory("safenav_sim")
    pkg_ros_gz_sim = get_package_share_directory("ros_gz_sim")
    pkg_turtlebot4_ignition_bringup = get_package_share_directory("turtlebot4_ignition_bringup")

    world_path = PathJoinSubstitution([pkg_safenav_sim, "worlds", "safenav_lab.sdf"])
    gui_config = PathJoinSubstitution(
        [pkg_turtlebot4_ignition_bringup, "gui", LaunchConfiguration("model"), "gui.config"])

    gz_sim_launch = PathJoinSubstitution([pkg_ros_gz_sim, "launch", "gz_sim.launch.py"])
    spawn_launch = PathJoinSubstitution(
        [pkg_turtlebot4_ignition_bringup, "launch", "turtlebot4_spawn.launch.py"])

    gazebo_gui = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([gz_sim_launch]),
        launch_arguments=[
            ("ign_args", [world_path, " -r -v 4 --gui-config ", gui_config]),
        ],
        condition=IfCondition(LaunchConfiguration("gui")),
    )
    gazebo_headless = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([gz_sim_launch]),
        launch_arguments=[
            ("ign_args", [world_path, " -r -s -v 4"]),
        ],
        condition=UnlessCondition(LaunchConfiguration("gui")),
    )

    clock_bridge = Node(
        package="ros_gz_bridge", executable="parameter_bridge", name="clock_bridge",
        output="screen",
        arguments=["/clock@rosgraph_msgs/msg/Clock[ignition.msgs.Clock"],
    )

    robot_spawn = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([spawn_launch]),
        launch_arguments=[
            ("model", LaunchConfiguration("model")),
            ("x", LaunchConfiguration("x")),
            ("y", LaunchConfiguration("y")),
            ("z", "0.0"),
            ("yaw", LaunchConfiguration("yaw")),
        ],
    )

    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(gazebo_gui)
    ld.add_action(gazebo_headless)
    ld.add_action(clock_bridge)
    ld.add_action(robot_spawn)
    return ld
