#ifndef SEMANTIC_WAYPOINT_PLANNER__ANNOTATION_GRAPH_HPP_
#define SEMANTIC_WAYPOINT_PLANNER__ANNOTATION_GRAPH_HPP_

#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace semantic_waypoint_planner
{

/// Thrown when a room_annotations.json document fails validation.
class GraphValidationError : public std::runtime_error
{
public:
  explicit GraphValidationError(const std::string & msg)
  : std::runtime_error(msg)
  {}
};

struct RoomPose
{
  double x = 0.0;
  double y = 0.0;
  double theta = 0.0;
  std::string frame = "map";
};

struct Room
{
  std::string name;
  std::vector<std::string> aliases;
  RoomPose pose;
  std::vector<std::string> tags;
  std::string parent;
};

struct Edge
{
  std::string from;
  std::string to;
  std::string relation;
};

/// C++ mirror of semantic_waypoint_planner.graph.AnnotationGraph (Python core, Phase 1).
/// Validation rules must stay identical: duplicate names, duplicate or colliding aliases,
/// non-finite poses, unknown edge endpoints are all rejected.
class AnnotationGraph
{
public:
  static AnnotationGraph from_file(const std::string & path);

  /// Validates then writes to disk atomically (temp file in the same directory, then rename).
  void save(const std::string & path) const;

  const std::vector<Room> & rooms() const {return rooms_;}
  const std::vector<Edge> & edges() const {return edges_;}
  const std::string & facility() const {return facility_;}
  const std::string & frame() const {return frame_;}

  std::vector<std::string> canonical_names() const;
  std::vector<std::string> all_aliases() const;

  std::optional<Room> get_room(const std::string & name) const;

  /// Returns the canonical name for an exact canonical name or alias match.
  std::optional<std::string> resolve_alias(const std::string & text) const;

  /// Throws GraphValidationError if the room duplicates an existing name or otherwise makes
  /// the document invalid. On success the room is appended and the alias index updated.
  void add_room(const Room & room);

private:
  std::string facility_;
  std::string frame_ = "map";
  std::vector<Room> rooms_;
  std::vector<Edge> edges_;
  std::map<std::string, std::string> alias_index_;  // alias -> canonical name

  void rebuild_index();
};

/// Validates a parsed JSON document against the room_annotations.json schema.
/// Throws GraphValidationError with a descriptive message on the first failure found.
void validate_document(const nlohmann::json & data);

}  // namespace semantic_waypoint_planner

#endif  // SEMANTIC_WAYPOINT_PLANNER__ANNOTATION_GRAPH_HPP_
