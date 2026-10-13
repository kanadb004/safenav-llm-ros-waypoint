"""Full command to navigation stack in loopback (D30: Gazebo does not work in the container):
the loopback simulator, map server, Nav2 (with semantic_waypoint_planner_bt_node in
bt_navigator's plugin_lib_names), the annotation map node, the Python LLM resolver, and the
operator facing semantic_goal_node. Use `say.py` or publish SemanticGoal on /semantic_goal.
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
    DeclareLaunchArgument("grammar_on", default_value="true"),
    DeclareLaunchArgument("model_path", default_value="phi3-mini-4k-instruct.Q4_K_M.gguf"),
    DeclareLaunchArgument("resolver_timeout_ms", default_value="300000"),
    DeclareLaunchArgument("fewshot_count", default_value="0"),
    DeclareLaunchArgument("n_threads", default_value="8"),
    DeclareLaunchArgument("backend", default_value="inprocess"),
    DeclareLaunchArgument("backend_url", default_value="http://host.docker.internal:8080"),
]


def generate_launch_description():
    pkg_safenav_sim = get_package_share_directory("safenav_sim")
    pkg_semantic_waypoint_planner = get_package_share_directory("semantic_waypoint_planner")
    pkg_nav2_bringup = get_package_share_directory("nav2_bringup")

    nav2_params = PathJoinSubstitution([pkg_safenav_sim, "config", "nav2_params.yaml"])
    planner_params = PathJoinSubstitution(
        [pkg_semantic_waypoint_planner, "config", "planner_params.yaml"])
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

    llm_resolver_node = Node(
        package="semantic_waypoint_planner",
        executable="llm_resolver.py",
        name="llm_resolver_node_py",
        output="screen",
        parameters=[planner_params, {
            "annotations_path": annotations_path,
            "model_path": LaunchConfiguration("model_path"),
            "grammar_on": LaunchConfiguration("grammar_on"),
            "timeout_ms": LaunchConfiguration("resolver_timeout_ms"),
            "fewshot_count": LaunchConfiguration("fewshot_count"),
            "n_threads": LaunchConfiguration("n_threads"),
            "backend": LaunchConfiguration("backend"),
            "backend_url": LaunchConfiguration("backend_url"),
        }],
    )

    semantic_goal_node = LifecycleNode(
        package="semantic_waypoint_planner",
        executable="semantic_goal_node",
        name="semantic_goal_node",
        namespace="",
        output="screen",
        parameters=[planner_params],
    )

    lifecycle_manager = Node(
        package="nav2_lifecycle_manager", executable="lifecycle_manager",
        name="lifecycle_manager_semantic_nav", output="screen",
        parameters=[{
            "autostart": True,
            "node_names": ["map_server", "semantic_goal_node"],
            # semantic_goal_node is a plain rclcpp_lifecycle::LifecycleNode, not
            # nav2_util::LifecycleNode, so it does not implement the bond protocol; 0.0 disables
            # the bond watchdog for both managed nodes rather than only partially working.
            "bond_timeout": 0.0,
        }],
    )

    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(loopback_sim_node)
    ld.add_action(map_server)
    ld.add_action(nav2)
    ld.add_action(annotation_map_node)
    ld.add_action(llm_resolver_node)
    ld.add_action(semantic_goal_node)
    ld.add_action(lifecycle_manager)
    return ld
