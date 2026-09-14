#include "rclcpp/rclcpp.hpp"
#include "semantic_waypoint_planner/annotation_map_node.hpp"

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<semantic_waypoint_planner::AnnotationMapNode>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
