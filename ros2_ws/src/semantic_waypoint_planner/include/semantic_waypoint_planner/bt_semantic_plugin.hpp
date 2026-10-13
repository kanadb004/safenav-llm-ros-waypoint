#ifndef SEMANTIC_WAYPOINT_PLANNER__BT_SEMANTIC_PLUGIN_HPP_
#define SEMANTIC_WAYPOINT_PLANNER__BT_SEMANTIC_PLUGIN_HPP_

#include <mutex>
#include <string>
#include <vector>

#include "behaviortree_cpp_v3/action_node.h"
#include "geometry_msgs/msg/pose_stamped.hpp"
#include "rclcpp/rclcpp.hpp"

#include "std_msgs/msg/string.hpp"

#include "semantic_waypoint_planner/msg/clarification_request.hpp"
#include "semantic_waypoint_planner/srv/list_rooms.hpp"
#include "semantic_waypoint_planner/srv/resolve_waypoint.hpp"

namespace semantic_waypoint_planner
{

/// Nav2 BT node (BehaviorTree.CPP v3 `BT::ActionNodeBase`) that calls `/list_rooms` then
/// `/resolve_waypoint` and blocks on the response up to `timeout_ms`. tick() never returns
/// RUNNING: the plan's DoD asks for a bounded blocking call rather than an asynchronous one,
/// and Nav2's bt_navigator tick loop (`bt_loop_duration`, default 10 ms) is fast enough that a
/// single blocking tick of a few seconds is visible in the log rather than stalling navigation
/// elsewhere. The service clients live on a private, not-spun-by-default callback group so the
/// blocking wait below does not race the executor that is already ticking bt_navigator's main
/// node.
class SemanticNavigateToPose : public BT::ActionNodeBase
{
public:
  SemanticNavigateToPose(const std::string & name, const BT::NodeConfiguration & config);

  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>("command"),
      BT::InputPort<double>("confidence_threshold", 0.72, "abstain below this"),
      BT::InputPort<int>("timeout_ms", 3000, "bounded wait on /resolve_waypoint"),
      BT::OutputPort<geometry_msgs::msg::PoseStamped>("resolved_pose"),
      BT::OutputPort<std::string>("resolved_room"),
      BT::OutputPort<double>("calibrated_confidence"),
    };
  }

  BT::NodeStatus tick() override;
  void halt() override;

private:
  void publish_clarification(
    const std::string & command, const std::string & resolved_room,
    double calibrated_confidence, const std::string & reason,
    const std::vector<std::string> & known_rooms);

  rclcpp::Node::SharedPtr node_;
  rclcpp::CallbackGroup::SharedPtr callback_group_;
  rclcpp::executors::SingleThreadedExecutor callback_group_executor_;

  rclcpp::Client<srv::ListRooms>::SharedPtr list_rooms_client_;
  rclcpp::Client<srv::ResolveWaypoint>::SharedPtr resolve_client_;
  rclcpp::Publisher<msg::ClarificationRequest>::SharedPtr clarification_pub_;
  // Not a section 12 interface: an internal side channel so semantic_goal_node can report the
  // resolved room and confidence in /semantic_goal_result, since NavigateToPose's result carries
  // only std_msgs/Empty (recorded as D45).
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr resolution_pub_;

  std::mutex pending_mutex_;
  int64_t pending_request_id_{-1};
};

}  // namespace semantic_waypoint_planner

#endif  // SEMANTIC_WAYPOINT_PLANNER__BT_SEMANTIC_PLUGIN_HPP_
