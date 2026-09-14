#include "semantic_waypoint_planner/annotation_graph.hpp"

#include <cmath>
#include <cstdio>
#include <fstream>
#include <regex>
#include <set>
#include <sstream>
#include <unistd.h>

namespace semantic_waypoint_planner
{

using nlohmann::json;

namespace
{

const std::regex kNameRe("^[a-z][a-z0-9_]*$");

std::string to_lower(const std::string & s)
{
  std::string out = s;
  for (auto & c : out) {
    c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  }
  return out;
}

json room_to_json(const Room & r)
{
  json j;
  j["name"] = r.name;
  j["aliases"] = r.aliases;
  j["pose"] = {{"x", r.pose.x}, {"y", r.pose.y}, {"theta", r.pose.theta}, {"frame", r.pose.frame}};
  j["tags"] = r.tags;
  j["parent"] = r.parent;
  return j;
}

Room room_from_json(const json & j)
{
  Room r;
  r.name = j.at("name").get<std::string>();
  if (j.contains("aliases")) {
    r.aliases = j.at("aliases").get<std::vector<std::string>>();
  }
  const auto & pose = j.at("pose");
  r.pose.x = pose.at("x").get<double>();
  r.pose.y = pose.at("y").get<double>();
  r.pose.theta = pose.at("theta").get<double>();
  r.pose.frame = pose.value("frame", std::string("map"));
  if (j.contains("tags")) {
    r.tags = j.at("tags").get<std::vector<std::string>>();
  }
  r.parent = j.value("parent", std::string(""));
  return r;
}

}  // namespace

void validate_document(const json & data)
{
  if (!data.is_object()) {
    throw GraphValidationError("document must be a JSON object");
  }
  if (!data.contains("rooms") || !data.at("rooms").is_array()) {
    throw GraphValidationError("document must have a 'rooms' array");
  }
  const auto & rooms = data.at("rooms");
  if (rooms.empty()) {
    throw GraphValidationError("'rooms' must not be empty");
  }

  std::set<std::string> seen_names;
  std::set<std::string> seen_aliases;

  for (size_t i = 0; i < rooms.size(); ++i) {
    const auto & r = rooms[i];
    if (!r.is_object()) {
      throw GraphValidationError("rooms[" + std::to_string(i) + "] must be an object");
    }
    if (!r.contains("name") || !r.at("name").is_string()) {
      throw GraphValidationError("rooms[" + std::to_string(i) + "] missing name");
    }
    const std::string name = r.at("name").get<std::string>();
    if (!std::regex_match(name, kNameRe)) {
      throw GraphValidationError(
        "rooms[" + std::to_string(i) + "] name '" + name + "' must be lowercase snake_case");
    }
    if (seen_names.count(name)) {
      throw GraphValidationError("duplicate room name: " + name);
    }
    seen_names.insert(name);

    if (r.contains("aliases")) {
      if (!r.at("aliases").is_array()) {
        throw GraphValidationError("rooms[" + std::to_string(i) + "] '" + name + "' aliases must be a list");
      }
      for (const auto & a : r.at("aliases")) {
        if (!a.is_string()) {
          throw GraphValidationError(
            "rooms[" + std::to_string(i) + "] '" + name + "' aliases must be strings");
        }
        const std::string alias = a.get<std::string>();
        if (alias != to_lower(alias)) {
          throw GraphValidationError("alias '" + alias + "' must be lowercase");
        }
        if (seen_aliases.count(alias)) {
          throw GraphValidationError("duplicate alias: " + alias);
        }
        seen_aliases.insert(alias);
      }
    }

    if (!r.contains("pose") || !r.at("pose").is_object()) {
      throw GraphValidationError("rooms[" + std::to_string(i) + "] '" + name + "' missing pose");
    }
    const auto & pose = r.at("pose");
    for (const char * key : {"x", "y", "theta"}) {
      if (!pose.contains(key) || !pose.at(key).is_number()) {
        throw GraphValidationError(
          "rooms[" + std::to_string(i) + "] '" + name + "' pose." + key + " must be a number");
      }
      const double value = pose.at(key).get<double>();
      if (!std::isfinite(value)) {
        throw GraphValidationError(
          "rooms[" + std::to_string(i) + "] '" + name + "' pose." + key + " must be finite");
      }
    }
  }

  // Aliases must not collide with any canonical name declared anywhere in the file.
  for (const auto & r : rooms) {
    if (!r.contains("aliases")) {continue;}
    for (const auto & a : r.at("aliases")) {
      const std::string alias = a.get<std::string>();
      if (seen_names.count(alias)) {
        throw GraphValidationError("alias '" + alias + "' collides with a canonical name");
      }
    }
  }

  if (data.contains("edges")) {
    if (!data.at("edges").is_array()) {
      throw GraphValidationError("'edges' must be a list");
    }
    const auto & edges = data.at("edges");
    for (size_t i = 0; i < edges.size(); ++i) {
      const auto & e = edges[i];
      if (!e.is_object()) {
        throw GraphValidationError("edges[" + std::to_string(i) + "] must be an object");
      }
      for (const char * key : {"from", "to", "relation"}) {
        if (!e.contains(key) || !e.at(key).is_string()) {
          throw GraphValidationError(
            "edges[" + std::to_string(i) + "] missing '" + std::string(key) + "'");
        }
      }
      const std::string from = e.at("from").get<std::string>();
      const std::string to = e.at("to").get<std::string>();
      if (!seen_names.count(from)) {
        throw GraphValidationError("edges[" + std::to_string(i) + "] unknown endpoint 'from': " + from);
      }
      if (!seen_names.count(to)) {
        throw GraphValidationError("edges[" + std::to_string(i) + "] unknown endpoint 'to': " + to);
      }
    }
  }
}

AnnotationGraph AnnotationGraph::from_file(const std::string & path)
{
  std::ifstream f(path);
  if (!f.is_open()) {
    throw GraphValidationError("cannot open annotations file: " + path);
  }
  json data;
  try {
    f >> data;
  } catch (const json::parse_error & e) {
    throw GraphValidationError(std::string("invalid JSON in annotations file: ") + e.what());
  }

  validate_document(data);

  AnnotationGraph graph;
  graph.facility_ = data.value("facility", std::string(""));
  graph.frame_ = data.value("frame", std::string("map"));
  for (const auto & r : data.at("rooms")) {
    graph.rooms_.push_back(room_from_json(r));
  }
  if (data.contains("edges")) {
    for (const auto & e : data.at("edges")) {
      Edge edge;
      edge.from = e.at("from").get<std::string>();
      edge.to = e.at("to").get<std::string>();
      edge.relation = e.at("relation").get<std::string>();
      graph.edges_.push_back(edge);
    }
  }
  graph.rebuild_index();
  return graph;
}

void AnnotationGraph::rebuild_index()
{
  alias_index_.clear();
  for (const auto & r : rooms_) {
    for (const auto & alias : r.aliases) {
      alias_index_[alias] = r.name;
    }
  }
}

void AnnotationGraph::save(const std::string & path) const
{
  json data;
  data["version"] = 1;
  data["facility"] = facility_;
  data["frame"] = frame_;
  data["rooms"] = json::array();
  for (const auto & r : rooms_) {
    data["rooms"].push_back(room_to_json(r));
  }
  data["edges"] = json::array();
  for (const auto & e : edges_) {
    data["edges"].push_back({{"from", e.from}, {"to", e.to}, {"relation", e.relation}});
  }

  // Validate before persisting so a bad in-memory state never hits disk.
  validate_document(data);

  const auto slash = path.find_last_of('/');
  const std::string dir = (slash == std::string::npos) ? "." : path.substr(0, slash);
  const std::string tmp_path = dir + "/.room_annotations." + std::to_string(::getpid()) + ".tmp";

  {
    std::ofstream f(tmp_path);
    if (!f.is_open()) {
      throw GraphValidationError("cannot open temp file for atomic write: " + tmp_path);
    }
    f << data.dump(2) << "\n";
  }
  if (std::rename(tmp_path.c_str(), path.c_str()) != 0) {
    std::remove(tmp_path.c_str());
    throw GraphValidationError("atomic rename failed for: " + path);
  }
}

std::vector<std::string> AnnotationGraph::canonical_names() const
{
  std::vector<std::string> out;
  out.reserve(rooms_.size());
  for (const auto & r : rooms_) {
    out.push_back(r.name);
  }
  return out;
}

std::vector<std::string> AnnotationGraph::all_aliases() const
{
  std::vector<std::string> out;
  for (const auto & r : rooms_) {
    out.insert(out.end(), r.aliases.begin(), r.aliases.end());
  }
  return out;
}

std::optional<Room> AnnotationGraph::get_room(const std::string & name) const
{
  for (const auto & r : rooms_) {
    if (r.name == name) {
      return r;
    }
  }
  return std::nullopt;
}

std::optional<std::string> AnnotationGraph::resolve_alias(const std::string & text) const
{
  for (const auto & r : rooms_) {
    if (r.name == text) {
      return text;
    }
  }
  const auto it = alias_index_.find(text);
  if (it != alias_index_.end()) {
    return it->second;
  }
  return std::nullopt;
}

void AnnotationGraph::add_room(const Room & room)
{
  for (const auto & r : rooms_) {
    if (r.name == room.name) {
      throw GraphValidationError("duplicate room name: " + room.name);
    }
  }
  json candidate;
  candidate["facility"] = facility_;
  candidate["frame"] = frame_;
  candidate["rooms"] = json::array();
  for (const auto & r : rooms_) {
    candidate["rooms"].push_back(room_to_json(r));
  }
  candidate["rooms"].push_back(room_to_json(room));
  candidate["edges"] = json::array();
  for (const auto & e : edges_) {
    candidate["edges"].push_back({{"from", e.from}, {"to", e.to}, {"relation", e.relation}});
  }
  validate_document(candidate);

  rooms_.push_back(room);
  for (const auto & alias : room.aliases) {
    alias_index_[alias] = room.name;
  }
}

}  // namespace semantic_waypoint_planner
