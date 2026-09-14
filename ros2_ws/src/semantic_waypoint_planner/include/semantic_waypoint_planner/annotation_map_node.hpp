#ifndef SEMANTIC_WAYPOINT_PLANNER__ANNOTATION_MAP_NODE_HPP_
#define SEMANTIC_WAYPOINT_PLANNER__ANNOTATION_MAP_NODE_HPP_

#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/empty.hpp"
#include "visualization_msgs/msg/marker_array.hpp"

#include "semantic_waypoint_planner/annotation_graph.hpp"
#include "semantic_waypoint_planner/srv/add_room.hpp"
#include "semantic_waypoint_planner/srv/get_room_pose.hpp"
#include "semantic_waypoint_planner/srv/list_rooms.hpp"

namespace semantic_waypoint_planner
{

/// Owns the annotation graph and serves /get_room_pose, /add_room, /list_rooms.
/// Publishes /semantic_markers (latched) and /annotation_graph_updated after every AddRoom.
class AnnotationMapNode : public rclcpp::Node
{
public:
  explicit AnnotationMapNode(const rclcpp::NodeOptions & options = rclcpp::NodeOptions());

private:
  void handle_get_room_pose(
    const std::shared_ptr<srv::GetRoomPose::Request> request,
    std::shared_ptr<srv::GetRoomPose::Response> response);

  void handle_add_room(
    const std::shared_ptr<srv::AddRoom::Request> request,
    std::shared_ptr<srv::AddRoom::Response> response);

  void handle_list_rooms(
    const std::shared_ptr<srv::ListRooms::Request> request,
    std::shared_ptr<srv::ListRooms::Response> response);

  void publish_markers();

  std::string resolve_annotations_path() const;

  std::unique_ptr<AnnotationGraph> graph_;
  std::string annotations_path_;

  rclcpp::Service<srv::GetRoomPose>::SharedPtr get_room_pose_srv_;
  rclcpp::Service<srv::AddRoom>::SharedPtr add_room_srv_;
  rclcpp::Service<srv::ListRooms>::SharedPtr list_rooms_srv_;
  rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr markers_pub_;
  rclcpp::Publisher<std_msgs::msg::Empty>::SharedPtr graph_updated_pub_;
};

}  // namespace semantic_waypoint_planner

#endif  // SEMANTIC_WAYPOINT_PLANNER__ANNOTATION_MAP_NODE_HPP_
