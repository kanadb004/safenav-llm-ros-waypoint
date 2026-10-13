"""Phase 6 DoD launch test: SemanticNavigateToPose, SpeakText and semantic_goal_node against a
real bt_navigator (pluginlib-free BT.CPP loading of semantic_waypoint_planner_bt_node) and a
deterministic stub resolver (test/fixtures/stub_resolver.py), standing in for the real
llm_resolver_node_py so this test does not load the GGUF model or stand up the full Nav2
planner/controller/costmap stack (not practical in a unit-level launch test; those are exercised
manually per the Phase 6 report against the real loopback sim stack).

Covers the three DoD paths: success (confidence above threshold, resolved_room set), low
confidence / unresolved (ClarificationRequest plus a /tts_text message listing known rooms, and
resolved_room left empty), and timeout (resolver pretends to be slow; same ClarificationRequest
path with reason "timeout"). nav_result is "succeeded" in all three cases: the top level
Fallback's SpeakText branch catches SemanticNavigateToPose's FAILURE and completes the tree, so
emptiness of resolved_room, not nav_result, is what distinguishes a real resolution from a
clarification.

Run with `colcon test --packages-select semantic_waypoint_planner`.
"""

import json
import os
import shutil
import tempfile
import time
import unittest

import launch
import launch_ros.actions
import launch_testing
import launch_testing.actions
import rclpy
from launch.actions import ExecuteProcess
from rclpy.node import Node
from rcl_interfaces.srv import SetParameters
from rcl_interfaces.msg import Parameter, ParameterValue, ParameterType
from std_msgs.msg import String

from semantic_waypoint_planner.msg import SemanticGoal

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BT_TEMPLATE = os.path.join(THIS_DIR, "bt", "test_minimal_template.xml")
STUB_RESOLVER = os.path.join(THIS_DIR, "fixtures", "stub_resolver.py")

RUNS_DIR = tempfile.mkdtemp(prefix="semantic_goal_node_test_runs_")


def generate_test_description():
    stub_resolver = ExecuteProcess(
        cmd=["python3", STUB_RESOLVER],
        output="screen",
    )

    static_tf = launch_ros.actions.Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        arguments=["0", "0", "0", "0", "0", "0", "map", "base_link"],
    )

    bt_navigator = launch_ros.actions.Node(
        package="nav2_bt_navigator",
        executable="bt_navigator",
        name="bt_navigator",
        output="screen",
        parameters=[{
            "use_sim_time": False,
            "global_frame": "map",
            "robot_base_frame": "base_link",
            "odom_topic": "odom",
            "bt_loop_duration": 10,
            "default_server_timeout": 20,
            "plugin_lib_names": ["semantic_waypoint_planner_bt_node"],
            "default_nav_to_pose_bt_xml": BT_TEMPLATE,
            # bt_navigator loads both default trees at activation regardless of which action is
            # used; this test's plugin_lib_names has none of the stock recovery/control node
            # plugins the real default_nav_through_poses tree needs, so point it at the same
            # minimal fixture tree instead. Never ticked in this test.
            "default_nav_through_poses_bt_xml": BT_TEMPLATE,
        }],
    )

    lifecycle_manager = launch_ros.actions.Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_test",
        output="screen",
        parameters=[{
            "autostart": True,
            "node_names": ["bt_navigator", "semantic_goal_node"],
            "bond_timeout": 0.0,
        }],
    )

    semantic_goal_node = launch_ros.actions.Node(
        package="semantic_waypoint_planner",
        executable="semantic_goal_node",
        name="semantic_goal_node",
        output="screen",
        parameters=[{
            "bt_template_path": BT_TEMPLATE,
            "runs_dir": RUNS_DIR,
            "default_timeout_ms": 5000,
        }],
    )

    return launch.LaunchDescription([
        stub_resolver,
        static_tf,
        bt_navigator,
        semantic_goal_node,
        lifecycle_manager,
        launch_testing.actions.ReadyToTest(),
    ]), {
        "stub_resolver": stub_resolver,
        "bt_navigator": bt_navigator,
        "semantic_goal_node": semantic_goal_node,
    }


class TestSemanticNav(unittest.TestCase):
    # One persistent client node and set of subscriptions for the whole class, not per test
    # method: destroying and recreating a node of the same name between tests was observed to
    # leave the remote LifecyclePublisher's matched-subscriber count referring to the just-torn-
    # down reader for a while, so the next test's fresh subscription lost its one and only
    # message rather than merely receiving it late. self.results accumulates across all tests
    # in send order, which is why test methods are numbered (test_1_, test_2_, ...) to fix
    # execution order and index into it.
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = Node("test_client")
        cls.goal_pub = cls.node.create_publisher(SemanticGoal, "/semantic_goal", 1)
        cls.results = []
        cls.tts_messages = []
        cls.result_sub = cls.node.create_subscription(
            String, "/semantic_goal_result", cls._on_result, 10)
        cls.tts_sub = cls.node.create_subscription(
            String, "/tts_text", cls._on_tts, 10)

        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            rclpy.spin_once(cls.node, timeout_sec=0.5)
            if (
                cls.node.count_subscribers("/semantic_goal") > 0 and
                cls.node.count_publishers("/semantic_goal_result") > 0 and
                cls.node.count_publishers("/tts_text") > 0
            ):
                break
        # Matched counts can be nonzero slightly before the DDS reader/writer pairing used for
        # delivery actually completes; give it a short settle margin.
        settle_deadline = time.monotonic() + 1.5
        while time.monotonic() < settle_deadline:
            rclpy.spin_once(cls.node, timeout_sec=0.1)

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()
        shutil.rmtree(RUNS_DIR, ignore_errors=True)

    @classmethod
    def _on_result(cls, msg):
        cls.results.append(json.loads(msg.data))

    @classmethod
    def _on_tts(cls, msg):
        cls.tts_messages.append(msg.data)

    def _send_goal(self, command, confidence_threshold=0.72):
        goal = SemanticGoal()
        goal.command = command
        goal.confidence_threshold = confidence_threshold
        self.goal_pub.publish(goal)

    def _wait_for_result(self, index, timeout=20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.2)
            if len(self.results) > index:
                return self.results[index]
        self.fail(f"no /semantic_goal_result received within {timeout}s")

    def test_1_success_path(self):
        self._send_goal("go to the kitchen")
        result = self._wait_for_result(0)
        self.assertEqual(result["nav_result"], "succeeded")
        self.assertEqual(result["resolved_room"], "kitchen")
        self.assertGreaterEqual(result["calibrated_confidence"], 0.72)

    def test_2_low_confidence_path(self):
        self._send_goal("go to the cafeteria")
        result = self._wait_for_result(1)
        # SemanticNavigateToPose itself returns FAILURE (checked via resolved_room being empty,
        # since no room was accepted), but the tree's top level Fallback catches that FAILURE
        # with the SpeakText clarification branch, so the tree and the NavigateToPose action
        # both report success: speaking a clarification is a completed goal, by design.
        self.assertEqual(result["nav_result"], "succeeded")
        self.assertEqual(result["resolved_room"], "")

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not self.tts_messages:
            rclpy.spin_once(self.node, timeout_sec=0.2)
        self.assertTrue(self.tts_messages, "/tts_text received no message")
        self.assertIn("kitchen", self.tts_messages[-1])

    def test_3_timeout_path(self):
        set_params_client = self.node.create_client(
            SetParameters, "/semantic_goal_node/set_parameters")
        self.assertTrue(set_params_client.wait_for_service(timeout_sec=10.0))
        request = SetParameters.Request()
        request.parameters = [Parameter(
            name="default_timeout_ms",
            value=ParameterValue(type=ParameterType.PARAMETER_INTEGER, integer_value=300),
        )]
        future = set_params_client.call_async(request)
        rclpy.spin_until_future_complete(self.node, future, timeout_sec=10.0)

        start = time.monotonic()
        self._send_goal("slow command")
        result = self._wait_for_result(2, timeout=5.0)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 5.0)
        # Same Fallback-masks-FAILURE reasoning as test_2: the tree still reports "succeeded"
        # (a timeout clarification is a completed goal), so emptiness of resolved_room is what
        # distinguishes this from the real success path.
        self.assertEqual(result["nav_result"], "succeeded")
        self.assertEqual(result["resolved_room"], "")


@launch_testing.post_shutdown_test()
class TestNodeShutdown(unittest.TestCase):
    def test_exit_code(self, proc_info, semantic_goal_node, bt_navigator):
        launch_testing.asserts.assertExitCodes(proc_info, process=semantic_goal_node)
        launch_testing.asserts.assertExitCodes(proc_info, process=bt_navigator)
