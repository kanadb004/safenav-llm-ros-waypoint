#include "semantic_waypoint_planner/bt_speak_text.hpp"

namespace semantic_waypoint_planner
{

SpeakText::SpeakText(const std::string & name, const BT::NodeConfiguration & config)
: BT::SyncActionNode(name, config)
{
  node_ = config.blackboard->get<rclcpp::Node::SharedPtr>("node");
  rclcpp::QoS qos(10);
  tts_pub_ = node_->create_publisher<std_msgs::msg::String>("/tts_text", qos);
}

BT::NodeStatus SpeakText::tick()
{
  std::string text;
  if (!getInput("text", text)) {
    text = "I need clarification about that command.";
  }
  std_msgs::msg::String msg;
  msg.data = text;
  tts_pub_->publish(msg);
  RCLCPP_INFO(node_->get_logger(), "SpeakText: %s", text.c_str());
  return BT::NodeStatus::SUCCESS;
}

}  // namespace semantic_waypoint_planner
