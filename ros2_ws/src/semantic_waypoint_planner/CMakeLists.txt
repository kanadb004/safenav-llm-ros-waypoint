cmake_minimum_required(VERSION 3.8)
project(semantic_waypoint_planner)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
if(NOT CMAKE_CXX_STANDARD_REQUIRED)
  set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(visualization_msgs REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(nlohmann_json REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/SemanticGoal.msg"
  "msg/ClarificationRequest.msg"
  "srv/ResolveWaypoint.srv"
  "srv/AddRoom.srv"
  "srv/ListRooms.srv"
  "srv/GetRoomPose.srv"
  DEPENDENCIES std_msgs geometry_msgs
)
rosidl_get_typesupport_target(cpp_typesupport_target ${PROJECT_NAME} "rosidl_typesupport_cpp")

# ---------------------------------------------------------------------------
# ROS free annotation graph core (also exercised directly by test_annotation_graph.cpp)
# ---------------------------------------------------------------------------
add_library(annotation_graph src/annotation_graph.cpp)
target_include_directories(annotation_graph PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
target_link_libraries(annotation_graph PUBLIC nlohmann_json::nlohmann_json)
target_compile_definitions(annotation_graph PRIVATE
  SEMANTIC_WAYPOINT_PLANNER_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
)

# ---------------------------------------------------------------------------
# annotation_map_node
# ---------------------------------------------------------------------------
add_executable(annotation_map_node src/annotation_map_node.cpp src/annotation_map_node_main.cpp)
target_include_directories(annotation_map_node PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
target_link_libraries(annotation_map_node
  annotation_graph
  "${cpp_typesupport_target}"
)
ament_target_dependencies(annotation_map_node
  rclcpp
  std_msgs
  geometry_msgs
  visualization_msgs
  ament_index_cpp
)

install(TARGETS annotation_map_node
  DESTINATION lib/${PROJECT_NAME}
)
install(TARGETS annotation_graph
  DESTINATION lib
)

# ---------------------------------------------------------------------------
# Python: ROS free core module, rclpy scripts
#
# rosidl_generate_interfaces() above already calls ament_python_install_package(${PROJECT_NAME})
# for the generated msg/srv bindings (an empty __init__.py plus msg/ and srv/ subpackages), so
# we cannot call it a second time for the same project name (duplicate CMake targets). Instead,
# graph.py is installed as an extra module into that same site-packages package directory.
# ---------------------------------------------------------------------------
install(FILES
  ${PROJECT_NAME}/graph.py
  ${PROJECT_NAME}/grammar.py
  ${PROJECT_NAME}/prompt.py
  ${PROJECT_NAME}/resolver_core.py
  DESTINATION ${PYTHON_INSTALL_DIR}/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/annotate_map.py
  scripts/llm_resolver.py
  DESTINATION lib/${PROJECT_NAME}
)
install(PROGRAMS
  scripts/semantic_cli.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME semantic_cli
)

install(DIRECTORY
  maps
  config
  launch
  DESTINATION share/${PROJECT_NAME}
)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_annotation_graph test/test_annotation_graph.cpp)
  target_link_libraries(test_annotation_graph annotation_graph)
  target_compile_definitions(test_annotation_graph PRIVATE
    SEMANTIC_WAYPOINT_PLANNER_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
  )

  find_package(launch_testing_ament_cmake REQUIRED)
  add_launch_test(test/test_annotation_map_node_launch.py)

  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_python_core test/python
    APPEND_ENV PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}
    # the globally installed launch_testing and launch_ros pytest11 plugins are incompatible
    # with this pytest version's hookspec and break collection even for plain tests. "slow"
    # tests need the real GGUF model and are excluded from colcon test; run them with
    # `pytest -m slow` directly (see DoD in docs/PLAN.md Phase 3).
    ENV "PYTEST_ADDOPTS=-p no:launch_testing -p no:launch_ros -m \"not slow\""
  )

  add_launch_test(test/test_resolver_only_launch.py TIMEOUT 600)
endif()

ament_export_include_directories(include)
ament_export_libraries(annotation_graph)
ament_export_dependencies(rclcpp std_msgs geometry_msgs visualization_msgs nlohmann_json)

ament_package()
