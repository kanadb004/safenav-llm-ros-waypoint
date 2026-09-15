#!/usr/bin/env python3
"""``llm_resolver_node_py``: rclpy service node serving ``/resolve_waypoint``.

Reads the shared ``room_annotations.json`` file directly (same file and default path as
``annotation_map_node``) rather than reconstructing the full graph from ``/list_rooms``, because
that service's flat ``all_aliases`` list has no per-room grouping and carries no edges, both of
which the prompt needs. ``/list_rooms`` is still called at startup as a readiness check and
``/annotation_graph_updated`` triggers a re-read of the file so a new room becomes resolvable
without a restart.
"""

import concurrent.futures
import os
import threading
import time

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Empty

from semantic_waypoint_planner.graph import AnnotationGraph
from semantic_waypoint_planner.resolver_core import ResolverCore
from semantic_waypoint_planner.srv import GetRoomPose, ListRooms, ResolveWaypoint


class LlmResolverNode(Node):
    def __init__(self):
        super().__init__("llm_resolver_node_py")

        share_dir = get_package_share_directory("semantic_waypoint_planner")
        default_annotations = os.path.join(share_dir, "maps", "room_annotations.json")

        self.declare_parameter("annotations_path", default_annotations)
        self.declare_parameter("model_path", "phi3-mini-4k-instruct.Q4_K_M.gguf")
        self.declare_parameter("n_ctx", 2048)
        self.declare_parameter("n_threads", 8)
        self.declare_parameter("temperature", 0.1)
        self.declare_parameter("max_tokens", 256)
        self.declare_parameter("timeout_ms", 20000)
        self.declare_parameter("grammar_on", True)
        self.declare_parameter("fewshot_count", 5)
        self.declare_parameter("prompt_template", "system_template.txt")
        self.declare_parameter("allow_none", True)
        self.declare_parameter("calibrator_path", "")
        # The container image has no CUDA/Metal build of llama.cpp (CPU only per CLAUDE.md); the
        # ResolverCore default of -1 (offload all layers) is for host tooling with Metal.
        self.declare_parameter("n_gpu_layers", 0)

        annotations_path = self.get_parameter("annotations_path").value
        model_path = self._resolve_model_path(self.get_parameter("model_path").value)
        template_name = self.get_parameter("prompt_template").value
        template_path = os.path.join(share_dir, "config", "prompts", template_name)
        fewshot_path = os.path.join(share_dir, "config", "prompts", "fewshot.jsonl")
        calibrator_path = self.get_parameter("calibrator_path").value or None

        self._annotations_path = annotations_path
        self._graph_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        graph = AnnotationGraph.from_file(annotations_path)

        self.get_logger().info(f"loading model from {model_path}")
        self.core = ResolverCore(
            model_path=model_path,
            graph=graph,
            n_ctx=self.get_parameter("n_ctx").value,
            n_threads=self.get_parameter("n_threads").value,
            temperature=self.get_parameter("temperature").value,
            max_tokens=self.get_parameter("max_tokens").value,
            fewshot_count=self.get_parameter("fewshot_count").value,
            prompt_template=template_path,
            fewshot_path=fewshot_path,
            allow_none=self.get_parameter("allow_none").value,
            calibrator_path=calibrator_path,
            n_gpu_layers=self.get_parameter("n_gpu_layers").value,
        )
        self.get_logger().info("model loaded")

        self._executor_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        cb_group = ReentrantCallbackGroup()

        self.get_room_pose_client = self.create_client(
            GetRoomPose, "/get_room_pose", callback_group=cb_group
        )
        self.list_rooms_client = self.create_client(
            ListRooms, "/list_rooms", callback_group=cb_group
        )

        self._check_annotation_node_ready()

        self.resolve_srv = self.create_service(
            ResolveWaypoint, "/resolve_waypoint", self._on_resolve, callback_group=cb_group
        )
        self.graph_updated_sub = self.create_subscription(
            Empty, "/annotation_graph_updated", self._on_graph_updated, 10, callback_group=cb_group
        )

    def _resolve_model_path(self, model_path: str) -> str:
        if os.path.isabs(model_path):
            return model_path
        models_dir = os.environ.get("SAFENAV_MODELS_DIR", "/ws/models")
        return os.path.join(models_dir, model_path)

    def _check_annotation_node_ready(self) -> None:
        if not self.list_rooms_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().warn("/list_rooms not available yet at startup")
            return
        future = self.list_rooms_client.call_async(ListRooms.Request())
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        if future.done() and future.result() is not None:
            n = len(future.result().canonical_names)
            self.get_logger().info(f"annotation node ready, {n} canonical names")

    def _on_graph_updated(self, _msg: Empty) -> None:
        self.get_logger().info("annotation graph updated, reloading")
        with self._graph_lock:
            graph = AnnotationGraph.from_file(self._annotations_path)
            self.core.set_graph(graph)

    def _on_resolve(self, request, response):
        timeout_ms = self.get_parameter("timeout_ms").value
        grammar_on = self.get_parameter("grammar_on").value
        candidates = list(request.candidate_room_names) or None

        def do_resolve():
            with self._graph_lock:
                graph = self.core.graph
            cands = candidates or graph.canonical_names
            with self._inference_lock:
                return self.core.resolve(
                    request.natural_language_command, cands, grammar_on=grammar_on
                )

        future = self._executor_pool.submit(do_resolve)
        try:
            result = future.result(timeout=timeout_ms / 1000.0)
        except concurrent.futures.TimeoutError:
            response.success = False
            response.reasoning = "timeout"
            response.resolver_mode = "llm_grammar" if grammar_on else "llm_free"
            return response

        response.matched_room_name = result.room
        response.raw_confidence = result.raw_confidence
        response.calibrated_confidence = result.calibrated_confidence
        response.reasoning = result.reasoning
        response.token_entropy = result.token_entropy
        response.inference_ms = result.latency_ms
        response.resolver_mode = result.mode
        response.out_of_graph = result.out_of_graph
        response.calibrator_loaded = result.calibrator_loaded
        response.top_k_rooms = [name for name, _ in result.room_ranking]
        response.top_k_scores = [float(score) for _, score in result.room_ranking]

        if result.room and result.room != "none":
            pose_response = self._get_room_pose(result.room)
            if pose_response is not None and pose_response.found:
                response.resolved_pose = pose_response.pose
                response.success = True
            else:
                response.success = False
                response.reasoning = response.reasoning or "resolved room has no known pose"
        else:
            response.success = False

        return response

    def _get_room_pose(self, name: str):
        # Polled rather than rclpy.spin_until_future_complete(self, ...): this runs inside a
        # service callback the outer MultiThreadedExecutor is already spinning, and nesting a
        # second spin on the same node here would race that executor for callback dispatch.
        # The ReentrantCallbackGroup lets another worker thread process the response meanwhile.
        if not self.get_room_pose_client.wait_for_service(timeout_sec=1.0):
            return None
        req = GetRoomPose.Request()
        req.name = name
        future = self.get_room_pose_client.call_async(req)
        deadline = self.get_clock().now().nanoseconds + int(1.0 * 1e9)
        while not future.done() and self.get_clock().now().nanoseconds < deadline:
            time.sleep(0.001)
        return future.result() if future.done() else None


def main(args=None):
    rclpy.init(args=args)
    node = LlmResolverNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
