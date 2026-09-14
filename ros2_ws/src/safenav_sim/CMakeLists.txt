cmake_minimum_required(VERSION 3.8)
project(safenav_sim)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

ament_python_install_package(${PROJECT_NAME})

install(PROGRAMS scripts/gen_world.py DESTINATION lib/${PROJECT_NAME} RENAME gen_world)
install(PROGRAMS scripts/gen_map.py DESTINATION lib/${PROJECT_NAME} RENAME gen_map)
install(PROGRAMS scripts/goto.py DESTINATION lib/${PROJECT_NAME} RENAME goto)
install(PROGRAMS scripts/tour.py DESTINATION lib/${PROJECT_NAME} RENAME tour)
install(PROGRAMS scripts/loopback_sim_node.py DESTINATION lib/${PROJECT_NAME} RENAME loopback_sim_node)

install(DIRECTORY
  worlds
  maps
  config
  launch
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_python test/python
    APPEND_ENV PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}
    ENV "PYTEST_ADDOPTS=-p no:launch_testing -p no:launch_ros"
  )
endif()

ament_package()
