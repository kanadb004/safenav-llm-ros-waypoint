#ifndef SEMANTIC_WAYPOINT_PLANNER__SEMANTIC_GOAL_NODE_HPP_
#define SEMANTIC_WAYPOINT_PLANNER__SEMANTIC_GOAL_NODE_HPP_

#include <map>
#include <mutex>
#include <string>

#include "nav2_msgs/action/navigate_to_pose.hpp"
#include "rclcpp/rclcpp.hpp"
#include "rclcpp_action/rclcpp_action.hpp"
#include "rclcpp_lifecycle/lifecycle_node.hpp"
#include "std_msgs/msg/string.hpp"

#include "semantic_waypoint_planner/msg/clarification_request.hpp"
#include "semantic_waypoint_planner/msg/semantic_goal.hpp"

namespace semantic_waypoint_planner
{

/// Operator facing entry point: subscribes /semantic_goal, renders the per goal BT XML (D6),
/// sends NavigateToPose with behavior_tree set to that file, republishes /clarification_request
/// as human readable text on /tts_text, and publishes one JSON line on /semantic_goal_result
/// per goal.
class SemanticGoalNode : public rclcpp_lifecycle::LifecycleNode
{
public:
  using NavigateToPose = nav2_msgs::action::NavigateToPose;
  using GoalHandle = rclcpp_action::ClientGoalHandle<NavigateToPose>;

  explicit SemanticGoalNode(const rclcpp::NodeOptions & options = rclcpp::NodeOptions());

  rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn
  on_configure(const rclcpp_lifecycle::State & state) override;
  rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn
  on_activate(const rclcpp_lifecycle::State & state) override;
  rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn
  on_deactivate(const rclcpp_lifecycle::State & state) override;
  rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn
  on_cleanup(const rclcpp_lifecycle::State & state) override;
  rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn
  on_shutdown(const rclcpp_lifecycle::State & state) override;

private:
  struct Resolution
  {
    std::string resolved_room;
    double raw_confidence{0.0};
    double calibrated_confidence{0.0};
  };

  void handle_semantic_goal(const msg::SemanticGoal::SharedPtr goal_msg);
  void handle_clarification(const msg::ClarificationRequest::SharedPtr msg);
  void handle_resolution_result(const std_msgs::msg::String::SharedPtr msg);

  std::string render_bt_xml(
    const std::string & command, double confidence_threshold, int timeout_ms) const;
  static std::string xml_escape(const std::string & text);
  void publish_result(
    const std::string & command, const std::string & resolved_room, double raw_confidence,
    double calibrated_confidence, const std::string & nav_result, double e2e_ms) const;

  std::string bt_template_;
  std::string runs_dir_;

  rclcpp::Subscription<msg::SemanticGoal>::SharedPtr goal_sub_;
  rclcpp::Subscription<msg::ClarificationRequest>::SharedPtr clarification_sub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr resolution_sub_;
  rclcpp_lifecycle::LifecyclePublisher<std_msgs::msg::String>::SharedPtr tts_pub_;
  rclcpp_lifecycle::LifecyclePublisher<std_msgs::msg::String>::SharedPtr result_pub_;

  rclcpp_action::Client<NavigateToPose>::SharedPtr nav_client_;

  // Keyed by command: /semantic_resolution_result arrives shortly before NavigateToPose's
  // result in the single-goal-at-a-time case this phase targets. Not safe for concurrent goals
  // with the same command text; out of scope for Phase 6 (single operator, one goal at a time).
  std::mutex resolutions_mutex_;
  std::map<std::string, Resolution> resolutions_;
};

}  // namespace semantic_waypoint_planner

#endif  // SEMANTIC_WAYPOINT_PLANNER__SEMANTIC_GOAL_NODE_HPP_
