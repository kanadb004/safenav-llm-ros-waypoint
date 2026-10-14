#include "semantic_waypoint_planner/bt_semantic_plugin.hpp"

#include <chrono>

#include "behaviortree_cpp_v3/bt_factory.h"
#include "nlohmann/json.hpp"

#include "semantic_waypoint_planner/bt_speak_text.hpp"

namespace semantic_waypoint_planner
{

SemanticNavigateToPose::SemanticNavigateToPose(
  const std::string & name, const BT::NodeConfiguration & config)
: BT::ActionNodeBase(name, config)
{
  node_ = config.blackboard->get<rclcpp::Node::SharedPtr>("node");

  // A private, not-added-to-the-main-executor callback group: the clients below are only ever
  // spun by callback_group_executor_ inside tick(), never by whatever executor is already
  // ticking bt_navigator's main node.
  callback_group_ = node_->create_callback_group(
    rclcpp::CallbackGroupType::MutuallyExclusive, false);
  callback_group_executor_.add_callback_group(callback_group_, node_->get_node_base_interface());

  list_rooms_client_ = node_->create_client<srv::ListRooms>(
    "/list_rooms", rmw_qos_profile_services_default, callback_group_);
  resolve_client_ = node_->create_client<srv::ResolveWaypoint>(
    "/resolve_waypoint", rmw_qos_profile_services_default, callback_group_);

  rclcpp::QoS qos(10);
  clarification_pub_ = node_->create_publisher<msg::ClarificationRequest>(
    "/clarification_request", qos);
  resolution_pub_ = node_->create_publisher<std_msgs::msg::String>(
    "/semantic_resolution_result", qos);
}

void SemanticNavigateToPose::publish_clarification(
  const std::string & command, const std::string & resolved_room,
  double calibrated_confidence, const std::string & reason,
  const std::vector<std::string> & known_rooms)
{
  msg::ClarificationRequest msg;
  msg.header.stamp = node_->now();
  msg.command = command;
  msg.resolved_room = resolved_room;
  msg.calibrated_confidence = static_cast<float>(calibrated_confidence);
  msg.reason = reason;
  msg.known_rooms = known_rooms;
  clarification_pub_->publish(msg);
}

BT::NodeStatus SemanticNavigateToPose::tick()
{
  std::string command;
  if (!getInput("command", command) || command.empty()) {
    RCLCPP_WARN(node_->get_logger(), "SemanticNavigateToPose: empty command, FAILURE");
    publish_clarification("", "", 0.0, "empty_command", {});
    return BT::NodeStatus::FAILURE;
  }

  double threshold = 0.85;
  getInput("confidence_threshold", threshold);
  int timeout_ms = 3000;
  getInput("timeout_ms", timeout_ms);
  const auto timeout = std::chrono::milliseconds(timeout_ms);

  std::vector<std::string> known_rooms;
  if (list_rooms_client_->wait_for_service(std::chrono::milliseconds(200))) {
    auto list_request = std::make_shared<srv::ListRooms::Request>();
    auto list_future = list_rooms_client_->async_send_request(list_request);
    if (callback_group_executor_.spin_until_future_complete(list_future, std::chrono::milliseconds(200)) ==
        rclcpp::FutureReturnCode::SUCCESS)
    {
      known_rooms = list_future.get()->canonical_names;
    } else {
      list_rooms_client_->remove_pending_request(list_future.request_id);
    }
  } else {
    RCLCPP_WARN(node_->get_logger(), "SemanticNavigateToPose: /list_rooms not available in 200 ms");
  }

  if (!resolve_client_->wait_for_service(timeout)) {
    RCLCPP_WARN(node_->get_logger(), "SemanticNavigateToPose: /resolve_waypoint not available, timeout");
    publish_clarification(command, "", 0.0, "timeout", known_rooms);
    return BT::NodeStatus::FAILURE;
  }

  auto request = std::make_shared<srv::ResolveWaypoint::Request>();
  request->natural_language_command = command;
  request->candidate_room_names = known_rooms;

  auto future = resolve_client_->async_send_request(request);
  {
    std::lock_guard<std::mutex> lock(pending_mutex_);
    pending_request_id_ = future.request_id;
  }

  const auto rc = callback_group_executor_.spin_until_future_complete(future, timeout);

  {
    std::lock_guard<std::mutex> lock(pending_mutex_);
    pending_request_id_ = -1;
  }

  if (rc != rclcpp::FutureReturnCode::SUCCESS) {
    resolve_client_->remove_pending_request(future.request_id);
    RCLCPP_WARN(node_->get_logger(), "SemanticNavigateToPose: /resolve_waypoint timed out for '%s'", command.c_str());
    publish_clarification(command, "", 0.0, "timeout", known_rooms);
    return BT::NodeStatus::FAILURE;
  }

  srv::ResolveWaypoint::Response::SharedPtr response;
  try {
    response = future.get();
  } catch (const std::exception & e) {
    // halt() raced this tick and removed the pending request, breaking the promise.
    RCLCPP_WARN(node_->get_logger(), "SemanticNavigateToPose: request cancelled: %s", e.what());
    publish_clarification(command, "", 0.0, "timeout", known_rooms);
    return BT::NodeStatus::FAILURE;
  }
  const double calibrated_confidence = static_cast<double>(response->calibrated_confidence);
  const bool gate_passed = response->success && calibrated_confidence >= threshold;

  // Phase 8 (D55): publish resolver telemetry whenever a response was actually received,
  // not only on gate pass, so the e2e150 suite can report out_of_graph rate, resolver_mode and
  // the gate's own accept/reject behaviour from /semantic_goal_result without a second source.
  // /semantic_resolution_result is the D46 side channel, not a frozen section 12 interface.
  // resolved_room keeps its pre-existing meaning (the room actually navigated to, empty unless
  // the gate passed); attempted_room is the new telemetry field carrying the resolver's match
  // regardless of gate outcome.
  const nlohmann::json resolution_json{
    {"command", command},
    {"resolved_room", gate_passed ? response->matched_room_name : std::string("")},
    {"attempted_room", response->matched_room_name},
    {"raw_confidence", static_cast<double>(response->raw_confidence)},
    {"calibrated_confidence", calibrated_confidence},
    {"resolver_mode", response->resolver_mode},
    {"out_of_graph", response->out_of_graph},
    {"token_entropy", static_cast<double>(response->token_entropy)},
    {"reasoning", response->reasoning},
    {"success", response->success},
    {"gate_passed", gate_passed},
    {"threshold_used", threshold},
  };
  std_msgs::msg::String resolution_msg;
  resolution_msg.data = resolution_json.dump();
  resolution_pub_->publish(resolution_msg);

  if (gate_passed) {
    setOutput("resolved_pose", response->resolved_pose);
    setOutput("resolved_room", response->matched_room_name);
    setOutput("calibrated_confidence", calibrated_confidence);
    RCLCPP_INFO(
      node_->get_logger(), "SemanticNavigateToPose: '%s' -> '%s' (confidence %.2f)",
      command.c_str(), response->matched_room_name.c_str(), calibrated_confidence);
    return BT::NodeStatus::SUCCESS;
  }

  const std::string reason = response->success ? "low_confidence" : "unresolved";
  RCLCPP_INFO(
    node_->get_logger(), "SemanticNavigateToPose: '%s' -> %s (confidence %.2f, threshold %.2f)",
    command.c_str(), reason.c_str(), calibrated_confidence, threshold);
  publish_clarification(command, response->matched_room_name, calibrated_confidence, reason, known_rooms);
  return BT::NodeStatus::FAILURE;
}

void SemanticNavigateToPose::halt()
{
  std::lock_guard<std::mutex> lock(pending_mutex_);
  if (pending_request_id_ != -1) {
    resolve_client_->remove_pending_request(pending_request_id_);
    pending_request_id_ = -1;
  }
}

}  // namespace semantic_waypoint_planner

BT_REGISTER_NODES(factory)
{
  factory.registerNodeType<semantic_waypoint_planner::SemanticNavigateToPose>(
    "SemanticNavigateToPose");
  factory.registerNodeType<semantic_waypoint_planner::SpeakText>("SpeakText");
}
