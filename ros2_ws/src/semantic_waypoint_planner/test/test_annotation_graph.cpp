#include <cstdio>
#include <fstream>
#include <string>

#include "gtest/gtest.h"
#include "semantic_waypoint_planner/annotation_graph.hpp"

using semantic_waypoint_planner::AnnotationGraph;
using semantic_waypoint_planner::GraphValidationError;
using semantic_waypoint_planner::Room;

namespace
{

std::string write_temp_json(const std::string & contents)
{
  const std::string path = "/tmp/test_annotation_graph_" + std::to_string(::getpid()) + ".json";
  std::ofstream f(path);
  f << contents;
  f.close();
  return path;
}

const char * kValidDoc = R"({
  "version": 1,
  "facility": "test_facility",
  "frame": "map",
  "rooms": [
    {"name": "room_a", "aliases": ["first room", "room one"],
     "pose": {"x": 1.0, "y": 2.0, "theta": 0.0, "frame": "map"},
     "tags": ["test"], "parent": "floor_1"},
    {"name": "room_b", "aliases": ["second room"],
     "pose": {"x": 3.0, "y": 4.0, "theta": 1.57, "frame": "map"},
     "tags": [], "parent": "floor_1"}
  ],
  "edges": [
    {"from": "room_a", "to": "room_b", "relation": "adjacent"}
  ]
})";

}  // namespace

TEST(AnnotationGraph, LoadsValidDocument)
{
  const auto path = write_temp_json(kValidDoc);
  auto graph = AnnotationGraph::from_file(path);
  EXPECT_EQ(graph.canonical_names().size(), 2u);
  EXPECT_EQ(graph.all_aliases().size(), 3u);
  std::remove(path.c_str());
}

TEST(AnnotationGraph, ResolvesCanonicalAndAlias)
{
  const auto path = write_temp_json(kValidDoc);
  auto graph = AnnotationGraph::from_file(path);
  ASSERT_TRUE(graph.resolve_alias("room_a").has_value());
  EXPECT_EQ(graph.resolve_alias("room_a").value(), "room_a");
  ASSERT_TRUE(graph.resolve_alias("first room").has_value());
  EXPECT_EQ(graph.resolve_alias("first room").value(), "room_a");
  EXPECT_FALSE(graph.resolve_alias("not_a_room").has_value());
  std::remove(path.c_str());
}

TEST(AnnotationGraph, GetRoomPose)
{
  const auto path = write_temp_json(kValidDoc);
  auto graph = AnnotationGraph::from_file(path);
  const auto room = graph.get_room("room_b");
  ASSERT_TRUE(room.has_value());
  EXPECT_DOUBLE_EQ(room->pose.x, 3.0);
  EXPECT_DOUBLE_EQ(room->pose.theta, 1.57);
  EXPECT_FALSE(graph.get_room("missing_room").has_value());
  std::remove(path.c_str());
}

TEST(AnnotationGraph, RejectsDuplicateName)
{
  const std::string doc = R"({
    "rooms": [
      {"name": "room_a", "aliases": [], "pose": {"x": 0, "y": 0, "theta": 0}},
      {"name": "room_a", "aliases": [], "pose": {"x": 1, "y": 1, "theta": 0}}
    ],
    "edges": []
  })";
  const auto path = write_temp_json(doc);
  EXPECT_THROW(AnnotationGraph::from_file(path), GraphValidationError);
  std::remove(path.c_str());
}

TEST(AnnotationGraph, RejectsDuplicateAlias)
{
  const std::string doc = R"({
    "rooms": [
      {"name": "room_a", "aliases": ["shared"], "pose": {"x": 0, "y": 0, "theta": 0}},
      {"name": "room_b", "aliases": ["shared"], "pose": {"x": 1, "y": 1, "theta": 0}}
    ],
    "edges": []
  })";
  const auto path = write_temp_json(doc);
  EXPECT_THROW(AnnotationGraph::from_file(path), GraphValidationError);
  std::remove(path.c_str());
}

TEST(AnnotationGraph, RejectsAliasCollidingWithName)
{
  const std::string doc = R"({
    "rooms": [
      {"name": "room_a", "aliases": ["room_b"], "pose": {"x": 0, "y": 0, "theta": 0}},
      {"name": "room_b", "aliases": [], "pose": {"x": 1, "y": 1, "theta": 0}}
    ],
    "edges": []
  })";
  const auto path = write_temp_json(doc);
  EXPECT_THROW(AnnotationGraph::from_file(path), GraphValidationError);
  std::remove(path.c_str());
}

TEST(AnnotationGraph, RejectsUnknownEdgeEndpoint)
{
  const std::string doc = R"({
    "rooms": [
      {"name": "room_a", "aliases": [], "pose": {"x": 0, "y": 0, "theta": 0}}
    ],
    "edges": [
      {"from": "room_a", "to": "nonexistent", "relation": "near"}
    ]
  })";
  const auto path = write_temp_json(doc);
  EXPECT_THROW(AnnotationGraph::from_file(path), GraphValidationError);
  std::remove(path.c_str());
}

TEST(AnnotationGraph, RejectsBadNameFormat)
{
  const std::string doc = R"({
    "rooms": [
      {"name": "Not Snake Case", "aliases": [], "pose": {"x": 0, "y": 0, "theta": 0}}
    ],
    "edges": []
  })";
  const auto path = write_temp_json(doc);
  EXPECT_THROW(AnnotationGraph::from_file(path), GraphValidationError);
  std::remove(path.c_str());
}

TEST(AnnotationGraph, RejectsMissingFile)
{
  EXPECT_THROW(AnnotationGraph::from_file("/nonexistent/path.json"), GraphValidationError);
}

TEST(AnnotationGraph, AddRoomSucceedsAndRejectsDuplicate)
{
  const auto path = write_temp_json(kValidDoc);
  auto graph = AnnotationGraph::from_file(path);

  Room new_room;
  new_room.name = "room_c";
  new_room.aliases = {"third room"};
  new_room.pose = {5.0, 6.0, 0.0, "map"};
  new_room.tags = {};
  new_room.parent = "floor_1";

  EXPECT_NO_THROW(graph.add_room(new_room));
  EXPECT_EQ(graph.canonical_names().size(), 3u);
  ASSERT_TRUE(graph.resolve_alias("third room").has_value());
  EXPECT_EQ(graph.resolve_alias("third room").value(), "room_c");

  EXPECT_THROW(graph.add_room(new_room), GraphValidationError);
  std::remove(path.c_str());
}

TEST(AnnotationGraph, SaveAtomicRoundtrip)
{
  const auto src_path = write_temp_json(kValidDoc);
  auto graph = AnnotationGraph::from_file(src_path);

  const std::string out_path = "/tmp/test_annotation_graph_out_" + std::to_string(::getpid()) + ".json";
  graph.save(out_path);

  auto reloaded = AnnotationGraph::from_file(out_path);
  EXPECT_EQ(reloaded.canonical_names(), graph.canonical_names());

  std::remove(src_path.c_str());
  std::remove(out_path.c_str());
}

TEST(AnnotationGraph, ShippedMapValidatesAndHasThirtyRooms)
{
  // The real room_annotations.json is installed to the package share directory at build time;
  // this test runs against the source tree copy so it works before `colcon build` installs it.
  const std::string path = std::string(SEMANTIC_WAYPOINT_PLANNER_SOURCE_DIR) +
    "/maps/room_annotations.json";
  auto graph = AnnotationGraph::from_file(path);
  EXPECT_EQ(graph.canonical_names().size(), 30u);
}
