#ifndef SEMANTIC_WAYPOINT_PLANNER__BT_SPEAK_TEXT_HPP_
#define SEMANTIC_WAYPOINT_PLANNER__BT_SPEAK_TEXT_HPP_

#include <string>

#include "behaviortree_cpp_v3/action_node.h"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/string.hpp"

namespace semantic_waypoint_planner
{

/// Sync BT action: publishes the `text` input port on `/tts_text`. The `espeak-ng` subprocess
/// and `/cmd_lightring` pattern named in the plan are optional extras this phase did not reach;
/// the topic alone is what the fallback subtree and the Phase 6 DoD need.
class SpeakText : public BT::SyncActionNode
{
public:
  SpeakText(const std::string & name, const BT::NodeConfiguration & config);

  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<std::string>("text", "what to say")};
  }

  BT::NodeStatus tick() override;

private:
  rclcpp::Node::SharedPtr node_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr tts_pub_;
};

}  // namespace semantic_waypoint_planner

#endif  // SEMANTIC_WAYPOINT_PLANNER__BT_SPEAK_TEXT_HPP_
