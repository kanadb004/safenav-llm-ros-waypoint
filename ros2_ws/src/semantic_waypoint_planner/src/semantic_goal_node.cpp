#include "semantic_waypoint_planner/semantic_goal_node.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <sstream>

#include "ament_index_cpp/get_package_share_directory.hpp"
#include "nlohmann/json.hpp"

namespace semantic_waypoint_planner
{

namespace
{
std::string read_file(const std::string & path)
{
  std::ifstream in(path);
  if (!in) {
    throw std::runtime_error("cannot open " + path);
  }
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

std::string replace_all(std::string text, const std::string & from, const std::string & to)
{
  size_t pos = 0;
  while ((pos = text.find(from, pos)) != std::string::npos) {
    text.replace(pos, from.size(), to);
    pos += to.size();
  }
  return text;
}
}  // namespace

SemanticGoalNode::SemanticGoalNode(const rclcpp::NodeOptions & options)
: rclcpp_lifecycle::LifecycleNode("semantic_goal_node", options)
{
  this->declare_parameter<std::string>("bt_template_path", "");
  this->declare_parameter<std::string>("runs_dir", "/ws/data/runs/bt");
  this->declare_parameter<int>("default_timeout_ms", 3000);
}

rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn
SemanticGoalNode::on_configure(const rclcpp_lifecycle::State &)
{
  std::string template_path;
  this->get_parameter("bt_template_path", template_path);
  if (template_path.empty()) {
    const std::string share_dir =
      ament_index_cpp::get_package_share_directory("semantic_waypoint_planner");
    template_path = share_dir + "/behavior_trees/semantic_navigate_to_pose.xml";
  }
  try {
    bt_template_ = read_file(template_path);
  } catch (const std::exception & e) {
    RCLCPP_ERROR(get_logger(), "failed to load BT template: %s", e.what());
    return rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn::FAILURE;
  }
  this->get_parameter("runs_dir", runs_dir_);

  tts_pub_ = this->create_publisher<std_msgs::msg::String>("/tts_text", rclcpp::QoS(10));
  result_pub_ = this->create_publisher<std_msgs::msg::String>(
    "/semantic_goal_result", rclcpp::QoS(10));

  goal_sub_ = this->create_subscription<msg::SemanticGoal>(
    "/semantic_goal", rclcpp::QoS(1).reliable(),
    std::bind(&SemanticGoalNode::handle_semantic_goal, this, std::placeholders::_1));
  clarification_sub_ = this->create_subscription<msg::ClarificationRequest>(
    "/clarification_request", rclcpp::QoS(10),
    std::bind(&SemanticGoalNode::handle_clarification, this, std::placeholders::_1));
  resolution_sub_ = this->create_subscription<std_msgs::msg::String>(
    "/semantic_resolution_result", rclcpp::QoS(10),
    std::bind(&SemanticGoalNode::handle_resolution_result, this, std::placeholders::_1));

  nav_client_ = rclcpp_action::create_client<NavigateToPose>(this, "navigate_to_pose");

  RCLCPP_INFO(get_logger(), "configured, BT template %s, runs_dir %s",
    template_path.c_str(), runs_dir_.c_str());
  return rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn::SUCCESS;
}

rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn
SemanticGoalNode::on_activate(const rclcpp_lifecycle::State &)
{
  tts_pub_->on_activate();
  result_pub_->on_activate();
  RCLCPP_INFO(get_logger(), "activated");
  return rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn::SUCCESS;
}

rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn
SemanticGoalNode::on_deactivate(const rclcpp_lifecycle::State &)
{
  tts_pub_->on_deactivate();
  result_pub_->on_deactivate();
  return rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn::SUCCESS;
}

rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn
SemanticGoalNode::on_cleanup(const rclcpp_lifecycle::State &)
{
  goal_sub_.reset();
  clarification_sub_.reset();
  tts_pub_.reset();
  result_pub_.reset();
  nav_client_.reset();
  return rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn::SUCCESS;
}

rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn
SemanticGoalNode::on_shutdown(const rclcpp_lifecycle::State &)
{
  return rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn::SUCCESS;
}

std::string SemanticGoalNode::xml_escape(const std::string & text)
{
  std::string out = replace_all(text, "&", "&amp;");
  out = replace_all(out, "\"", "&quot;");
  out = replace_all(out, "<", "&lt;");
  out = replace_all(out, ">", "&gt;");
  return out;
}

std::string SemanticGoalNode::render_bt_xml(
  const std::string & command, double confidence_threshold, int timeout_ms) const
{
  std::string xml = bt_template_;
  xml = replace_all(xml, "__COMMAND__", xml_escape(command));
  xml = replace_all(xml, "__CONFIDENCE_THRESHOLD__", std::to_string(confidence_threshold));
  xml = replace_all(xml, "__TIMEOUT_MS__", std::to_string(timeout_ms));
  return xml;
}

void SemanticGoalNode::handle_semantic_goal(const msg::SemanticGoal::SharedPtr goal_msg)
{
  const auto t_start = this->now();
  const std::string & command = goal_msg->command;

  if (command.empty()) {
    RCLCPP_WARN(get_logger(), "empty /semantic_goal command, ignoring");
    publish_result(command, "", 0.0, 0.0, "rejected_empty_command", 0.0);
    return;
  }

  double confidence_threshold = goal_msg->confidence_threshold;
  int timeout_ms = 3000;
  this->get_parameter("default_timeout_ms", timeout_ms);

  const std::string xml = render_bt_xml(command, confidence_threshold, timeout_ms);

  const auto now_ns = this->now().nanoseconds();
  const std::string bt_path = runs_dir_ + "/" + std::to_string(now_ns) + ".xml";
  std::filesystem::create_directories(runs_dir_);
  std::ofstream out(bt_path);
  if (!out) {
    RCLCPP_ERROR(get_logger(), "cannot write rendered BT XML to %s", bt_path.c_str());
    publish_result(command, "", 0.0, 0.0, "rejected_io_error", 0.0);
    return;
  }
  out << xml;
  out.close();

  if (!nav_client_->wait_for_action_server(std::chrono::seconds(5))) {
    RCLCPP_ERROR(get_logger(), "navigate_to_pose action server not available");
    publish_result(command, "", 0.0, 0.0, "rejected_no_action_server", 0.0);
    return;
  }

  NavigateToPose::Goal nav_goal;
  nav_goal.pose.header.frame_id = "map";
  nav_goal.pose.header.stamp = this->now();
  // Ignored: this tree never reads {goal}, it reads {resolved_pose} set by
  // SemanticNavigateToPose. The pose field is a required part of the action message.
  nav_goal.pose.pose.orientation.w = 1.0;
  nav_goal.behavior_tree = bt_path;

  auto send_goal_options = rclcpp_action::Client<NavigateToPose>::SendGoalOptions();
  send_goal_options.result_callback =
    [this, command, t_start](const GoalHandle::WrappedResult & wrapped_result) {
      std::string nav_result;
      switch (wrapped_result.code) {
        case rclcpp_action::ResultCode::SUCCEEDED:
          nav_result = "succeeded";
          break;
        case rclcpp_action::ResultCode::ABORTED:
          nav_result = "failed";
          break;
        case rclcpp_action::ResultCode::CANCELED:
          nav_result = "canceled";
          break;
        default:
          nav_result = "unknown";
          break;
      }
      const double e2e_ms = (this->now() - t_start).nanoseconds() / 1.0e6;
      Resolution resolution;
      {
        std::lock_guard<std::mutex> lock(resolutions_mutex_);
        auto it = resolutions_.find(command);
        if (it != resolutions_.end()) {
          resolution = it->second;
          resolutions_.erase(it);
        }
      }
      publish_result(
        command, resolution.resolved_room, resolution.raw_confidence,
        resolution.calibrated_confidence, nav_result, e2e_ms);
    };

  nav_client_->async_send_goal(nav_goal, send_goal_options);
  RCLCPP_INFO(get_logger(), "sent NavigateToPose for '%s' with bt %s", command.c_str(), bt_path.c_str());
}

void SemanticGoalNode::handle_resolution_result(const std_msgs::msg::String::SharedPtr msg)
{
  try {
    const auto j = nlohmann::json::parse(msg->data);
    Resolution resolution;
    resolution.resolved_room = j.at("resolved_room").get<std::string>();
    resolution.raw_confidence = j.at("raw_confidence").get<double>();
    resolution.calibrated_confidence = j.at("calibrated_confidence").get<double>();
    const std::string command = j.at("command").get<std::string>();
    std::lock_guard<std::mutex> lock(resolutions_mutex_);
    resolutions_[command] = resolution;
  } catch (const std::exception & e) {
    RCLCPP_WARN(get_logger(), "malformed /semantic_resolution_result: %s", e.what());
  }
}

void SemanticGoalNode::handle_clarification(const msg::ClarificationRequest::SharedPtr msg)
{
  std::ostringstream text;
  if (msg->reason == "timeout") {
    text << "I timed out trying to understand that command.";
  } else if (msg->reason == "empty_command") {
    text << "I did not hear a command.";
  } else {
    text << "I am not sure which location you mean.";
  }
  if (!msg->known_rooms.empty()) {
    text << " I know: ";
    for (size_t i = 0; i < msg->known_rooms.size(); ++i) {
      if (i > 0) {
        text << ", ";
      }
      text << msg->known_rooms[i];
    }
    text << ". Could you rephrase?";
  }

  std_msgs::msg::String out;
  out.data = text.str();
  if (tts_pub_->is_activated()) {
    tts_pub_->publish(out);
  }
  RCLCPP_INFO(get_logger(), "clarification (%s): %s", msg->reason.c_str(), out.data.c_str());
}

void SemanticGoalNode::publish_result(
  const std::string & command, const std::string & resolved_room, double raw_confidence,
  double calibrated_confidence, const std::string & nav_result, double e2e_ms) const
{
  const nlohmann::json j{
    {"command", command},
    {"resolved_room", resolved_room},
    {"raw_confidence", raw_confidence},
    {"calibrated_confidence", calibrated_confidence},
    {"nav_result", nav_result},
    {"e2e_ms", e2e_ms},
  };
  std_msgs::msg::String out;
  out.data = j.dump();
  if (result_pub_->is_activated()) {
    result_pub_->publish(out);
  }
}

}  // namespace semantic_waypoint_planner
