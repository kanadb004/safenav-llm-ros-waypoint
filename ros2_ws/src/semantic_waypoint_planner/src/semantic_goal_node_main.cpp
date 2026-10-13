#include "rclcpp/rclcpp.hpp"
#include "semantic_waypoint_planner/semantic_goal_node.hpp"

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<semantic_waypoint_planner::SemanticGoalNode>();
  rclcpp::spin(node->get_node_base_interface());
  rclcpp::shutdown();
  return 0;
}
