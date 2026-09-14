"""Map server, AMCL, Nav2 bringup, and the annotation map node, for use with sim.launch.py
(Gazebo) or a real robot. The loopback simulator publishes its own map -> odom transform and
does not need this launch file's AMCL; see loopback_sim.launch.py instead.
"""

import math

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, TimerAction
from launch.actions import ExecuteProcess
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node

ARGUMENTS = [
    DeclareLaunchArgument("rviz", default_value="false", choices=["true", "false"]),
    DeclareLaunchArgument("use_sim_time", default_value="true", choices=["true", "false"]),
    DeclareLaunchArgument("initial_x", default_value="1.0"),
    DeclareLaunchArgument("initial_y", default_value="6.0"),
    DeclareLaunchArgument("initial_yaw", default_value="0.0"),
]


def generate_launch_description():
    pkg_safenav_sim = get_package_share_directory("safenav_sim")
    pkg_semantic_waypoint_planner = get_package_share_directory("semantic_waypoint_planner")
    pkg_turtlebot4_navigation = get_package_share_directory("turtlebot4_navigation")
    pkg_turtlebot4_viz = get_package_share_directory("turtlebot4_viz")

    nav2_params = PathJoinSubstitution([pkg_safenav_sim, "config", "nav2_params.yaml"])
    map_yaml = PathJoinSubstitution([pkg_safenav_sim, "maps", "safenav_lab.yaml"])
    annotations_path = PathJoinSubstitution(
        [pkg_semantic_waypoint_planner, "maps", "room_annotations.json"])

    use_sim_time = LaunchConfiguration("use_sim_time")

    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            [pkg_turtlebot4_navigation, "/launch/localization.launch.py"]),
        launch_arguments={
            "use_sim_time": use_sim_time,
            "map": map_yaml,
            "params": nav2_params,
        }.items(),
    )

    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            [pkg_turtlebot4_navigation, "/launch/nav2.launch.py"]),
        launch_arguments={
            "use_sim_time": use_sim_time,
            "params_file": nav2_params,
        }.items(),
    )

    annotation_map_node = Node(
        package="semantic_waypoint_planner",
        executable="annotation_map_node",
        name="annotation_map_node",
        output="screen",
        parameters=[{"annotations_path": annotations_path}],
    )

    def make_initial_pose_pub(context, *args, **kwargs):
        x = float(LaunchConfiguration("initial_x").perform(context))
        y = float(LaunchConfiguration("initial_y").perform(context))
        yaw = float(LaunchConfiguration("initial_yaw").perform(context))
        qz, qw = math.sin(yaw / 2.0), math.cos(yaw / 2.0)
        yaml_arg = (
            f"{{header: {{frame_id: map}}, pose: {{pose: {{position: {{x: {x}, y: {y}, "
            f"z: 0.0}}, orientation: {{z: {qz}, w: {qw}}}}}}}}}"
        )
        return [ExecuteProcess(
            cmd=["ros2", "topic", "pub", "--once", "/initialpose",
                 "geometry_msgs/msg/PoseWithCovarianceStamped", yaml_arg],
        )]

    set_initial_pose = TimerAction(period=6.0, actions=[OpaqueFunction(function=make_initial_pose_pub)])

    rviz = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([pkg_turtlebot4_viz, "/launch/view_robot.launch.py"]),
        launch_arguments={"use_sim_time": use_sim_time}.items(),
        condition=IfCondition(LaunchConfiguration("rviz")),
    )

    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(localization)
    ld.add_action(nav2)
    ld.add_action(annotation_map_node)
    ld.add_action(set_initial_pose)
    ld.add_action(rviz)
    return ld
