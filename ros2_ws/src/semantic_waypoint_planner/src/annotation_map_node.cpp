#include "semantic_waypoint_planner/annotation_map_node.hpp"

#include <cmath>
#include <cstdlib>

#include "ament_index_cpp/get_package_share_directory.hpp"
#include "rclcpp/qos.hpp"

namespace semantic_waypoint_planner
{

namespace
{

/// Yaw only quaternion, matching the annotation graph's 2D theta pose convention.
void yaw_to_quaternion(double theta, geometry_msgs::msg::Quaternion & q)
{
  q.x = 0.0;
  q.y = 0.0;
  q.z = std::sin(theta / 2.0);
  q.w = std::cos(theta / 2.0);
}

double quaternion_to_yaw(const geometry_msgs::msg::Quaternion & q)
{
  // Pure yaw rotation assumed (2D annotation poses never carry roll or pitch).
  return 2.0 * std::atan2(q.z, q.w);
}

}  // namespace

AnnotationMapNode::AnnotationMapNode(const rclcpp::NodeOptions & options)
: rclcpp::Node("annotation_map_node", options)
{
  this->declare_parameter<std::string>("annotations_path", "");
  annotations_path_ = resolve_annotations_path();

  RCLCPP_INFO(get_logger(), "loading annotations from %s", annotations_path_.c_str());
  try {
    graph_ = std::make_unique<AnnotationGraph>(AnnotationGraph::from_file(annotations_path_));
  } catch (const GraphValidationError & e) {
    RCLCPP_ERROR(get_logger(), "invalid annotations file: %s", e.what());
    std::exit(1);
  }
  RCLCPP_INFO(
    get_logger(), "loaded %zu rooms from %s",
    graph_->rooms().size(), annotations_path_.c_str());

  rclcpp::QoS latched_qos(1);
  latched_qos.transient_local();
  latched_qos.reliable();

  markers_pub_ = create_publisher<visualization_msgs::msg::MarkerArray>(
    "/semantic_markers", latched_qos);
  graph_updated_pub_ = create_publisher<std_msgs::msg::Empty>(
    "/annotation_graph_updated", latched_qos);

  get_room_pose_srv_ = create_service<srv::GetRoomPose>(
    "/get_room_pose",
    std::bind(
      &AnnotationMapNode::handle_get_room_pose, this,
      std::placeholders::_1, std::placeholders::_2));
  add_room_srv_ = create_service<srv::AddRoom>(
    "/add_room",
    std::bind(
      &AnnotationMapNode::handle_add_room, this,
      std::placeholders::_1, std::placeholders::_2));
  list_rooms_srv_ = create_service<srv::ListRooms>(
    "/list_rooms",
    std::bind(
      &AnnotationMapNode::handle_list_rooms, this,
      std::placeholders::_1, std::placeholders::_2));

  publish_markers();
}

std::string AnnotationMapNode::resolve_annotations_path() const
{
  std::string param_value;
  this->get_parameter("annotations_path", param_value);
  if (!param_value.empty()) {
    return param_value;
  }
  const std::string share_dir =
    ament_index_cpp::get_package_share_directory("semantic_waypoint_planner");
  return share_dir + "/maps/room_annotations.json";
}

void AnnotationMapNode::handle_get_room_pose(
  const std::shared_ptr<srv::GetRoomPose::Request> request,
  std::shared_ptr<srv::GetRoomPose::Response> response)
{
  const auto room = graph_->get_room(request->name);
  if (!room) {
    response->found = false;
    return;
  }
  response->found = true;
  response->pose.header.frame_id = room->pose.frame;
  response->pose.header.stamp = this->now();
  response->pose.pose.position.x = room->pose.x;
  response->pose.pose.position.y = room->pose.y;
  response->pose.pose.position.z = 0.0;
  yaw_to_quaternion(room->pose.theta, response->pose.pose.orientation);
}

void AnnotationMapNode::handle_add_room(
  const std::shared_ptr<srv::AddRoom::Request> request,
  std::shared_ptr<srv::AddRoom::Response> response)
{
  Room room;
  room.name = request->name;
  room.aliases = request->aliases;
  room.pose.x = request->pose.position.x;
  room.pose.y = request->pose.position.y;
  room.pose.theta = quaternion_to_yaw(request->pose.orientation);
  room.pose.frame = graph_->frame();
  room.tags = request->tags;
  room.parent = request->parent;

  try {
    graph_->add_room(room);
  } catch (const GraphValidationError & e) {
    response->success = false;
    response->message = e.what();
    return;
  }

  try {
    graph_->save(annotations_path_);
  } catch (const GraphValidationError & e) {
    response->success = false;
    response->message = std::string("added in memory but failed to persist: ") + e.what();
    return;
  }

  response->success = true;
  response->message = "added room " + room.name;

  publish_markers();
  std_msgs::msg::Empty empty_msg;
  graph_updated_pub_->publish(empty_msg);
}

void AnnotationMapNode::handle_list_rooms(
  const std::shared_ptr<srv::ListRooms::Request> /*request*/,
  std::shared_ptr<srv::ListRooms::Response> response)
{
  response->canonical_names = graph_->canonical_names();
  response->all_aliases = graph_->all_aliases();
}

void AnnotationMapNode::publish_markers()
{
  visualization_msgs::msg::MarkerArray array;
  int id = 0;
  const auto stamp = this->now();
  for (const auto & room : graph_->rooms()) {
    visualization_msgs::msg::Marker marker;
    marker.header.frame_id = room.pose.frame;
    marker.header.stamp = stamp;
    marker.ns = "semantic_waypoint_planner";
    marker.id = id++;
    marker.type = visualization_msgs::msg::Marker::TEXT_VIEW_FACING;
    marker.action = visualization_msgs::msg::Marker::ADD;
    marker.pose.position.x = room.pose.x;
    marker.pose.position.y = room.pose.y;
    marker.pose.position.z = 0.5;
    yaw_to_quaternion(room.pose.theta, marker.pose.orientation);
    marker.scale.z = 0.3;
    marker.color.r = 1.0f;
    marker.color.g = 1.0f;
    marker.color.b = 1.0f;
    marker.color.a = 1.0f;
    marker.text = room.name;
    array.markers.push_back(marker);
  }
  markers_pub_->publish(array);
}

}  // namespace semantic_waypoint_planner
