"""Annotation map node plus the Python LLM resolver, no Nav2 and no sim: for manual
``semantic_cli`` checks and the Phase 3 launch test."""

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node

ARGUMENTS = [
    DeclareLaunchArgument("grammar_on", default_value="true"),
    DeclareLaunchArgument("model_path", default_value="phi3-mini-4k-instruct.Q4_K_M.gguf"),
    DeclareLaunchArgument("timeout_ms", default_value="300000"),
    DeclareLaunchArgument("fewshot_count", default_value="5"),
    DeclareLaunchArgument("n_threads", default_value="8"),
]


def generate_launch_description():
    pkg_share = get_package_share_directory("semantic_waypoint_planner")
    annotations_path = PathJoinSubstitution([pkg_share, "maps", "room_annotations.json"])

    annotation_map_node = Node(
        package="semantic_waypoint_planner",
        executable="annotation_map_node",
        name="annotation_map_node",
        output="screen",
        parameters=[{"annotations_path": annotations_path}],
    )

    llm_resolver_node = Node(
        package="semantic_waypoint_planner",
        executable="llm_resolver.py",
        name="llm_resolver_node_py",
        output="screen",
        parameters=[{
            "annotations_path": annotations_path,
            "model_path": LaunchConfiguration("model_path"),
            "grammar_on": LaunchConfiguration("grammar_on"),
            "timeout_ms": LaunchConfiguration("timeout_ms"),
            "fewshot_count": LaunchConfiguration("fewshot_count"),
            "n_threads": LaunchConfiguration("n_threads"),
        }],
    )

    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(annotation_map_node)
    ld.add_action(llm_resolver_node)
    return ld
