"""Fast batch experiment stack: the loopback simulator (odom, scan, map -> odom TF) plus
Nav2 and the annotation map node, no Gazebo and no AMCL (the loopback node is the localizer).
Used for the 150 run batches in Phase 8 and any experiment where Gazebo speed is a bottleneck.
"""

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import LifecycleNode, Node

ARGUMENTS = [
    DeclareLaunchArgument("initial_x", default_value="1.0"),
    DeclareLaunchArgument("initial_y", default_value="6.0"),
    DeclareLaunchArgument("initial_theta", default_value="0.0"),
]


def generate_launch_description():
    pkg_safenav_sim = get_package_share_directory("safenav_sim")
    pkg_semantic_waypoint_planner = get_package_share_directory("semantic_waypoint_planner")
    pkg_nav2_bringup = get_package_share_directory("nav2_bringup")

    nav2_params = PathJoinSubstitution([pkg_safenav_sim, "config", "nav2_params.yaml"])
    map_yaml = PathJoinSubstitution([pkg_safenav_sim, "maps", "safenav_lab.yaml"])
    annotations_path = PathJoinSubstitution(
        [pkg_semantic_waypoint_planner, "maps", "room_annotations.json"])

    loopback_sim_node = Node(
        package="safenav_sim",
        executable="loopback_sim_node",
        name="loopback_sim_node",
        output="screen",
        parameters=[{
            "map_yaml": map_yaml,
            "initial_x": LaunchConfiguration("initial_x"),
            "initial_y": LaunchConfiguration("initial_y"),
            "initial_theta": LaunchConfiguration("initial_theta"),
        }],
    )

    map_server = LifecycleNode(
        package="nav2_map_server", executable="map_server", name="map_server",
        namespace="", output="screen",
        parameters=[{"yaml_filename": map_yaml, "use_sim_time": False}],
    )
    map_server_lifecycle_manager = Node(
        package="nav2_lifecycle_manager", executable="lifecycle_manager",
        name="lifecycle_manager_map_server", output="screen",
        parameters=[{"autostart": True, "node_names": ["map_server"]}],
    )

    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            [pkg_nav2_bringup, "/launch/navigation_launch.py"]),
        launch_arguments={
            "use_sim_time": "False",
            "params_file": nav2_params,
            "use_composition": "False",
        }.items(),
    )

    annotation_map_node = Node(
        package="semantic_waypoint_planner",
        executable="annotation_map_node",
        name="annotation_map_node",
        output="screen",
        parameters=[{"annotations_path": annotations_path}],
    )

    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(loopback_sim_node)
    ld.add_action(map_server)
    ld.add_action(map_server_lifecycle_manager)
    ld.add_action(nav2)
    ld.add_action(annotation_map_node)
    return ld
