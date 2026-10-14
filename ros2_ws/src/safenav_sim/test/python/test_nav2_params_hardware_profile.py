import os

import yaml

PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SIM_PARAMS_PATH = os.path.join(PKG_ROOT, "config", "nav2_params.yaml")
HARDWARE_PARAMS_PATH = os.path.join(PKG_ROOT, "config", "nav2_params_hardware.yaml")

# PLAN.md section 15 (Phase 9): "Create 3 velocity limits restored to 0.26 m/s, reversing D10
# for hardware only", nothing else. These are the only scalar leaves that may differ.
VELOCITY_PATHS = [
    ("controller_server", "ros__parameters", "FollowPath", "max_vel_x"),
    ("controller_server", "ros__parameters", "FollowPath", "max_speed_xy"),
]
VELOCITY_LIST_PATHS = [
    ("velocity_smoother", "ros__parameters", "max_velocity", 0),
    ("velocity_smoother", "ros__parameters", "min_velocity", 0),
]


def _get(doc, path):
    for key in path:
        doc = doc[key]
    return doc


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_both_profiles_load_and_validate():
    sim = _load(SIM_PARAMS_PATH)
    hardware = _load(HARDWARE_PARAMS_PATH)
    assert "controller_server" in sim and "controller_server" in hardware
    assert "velocity_smoother" in sim and "velocity_smoother" in hardware


def test_hardware_velocity_limits_are_stock_turtlebot4_default():
    hardware = _load(HARDWARE_PARAMS_PATH)
    for path in VELOCITY_PATHS:
        assert _get(hardware, path) == 0.26, f"{'.'.join(path)} should be 0.26 on hardware"
    for path in VELOCITY_LIST_PATHS:
        *parent_path, idx = path
        value = _get(hardware, parent_path)[idx]
        assert abs(value) == 0.26, f"{'.'.join(map(str, path))} should be +/-0.26 on hardware"


def test_sim_and_hardware_differ_only_in_the_documented_velocity_fields():
    sim = _load(SIM_PARAMS_PATH)
    hardware = _load(HARDWARE_PARAMS_PATH)

    for path in VELOCITY_PATHS:
        assert _get(sim, path) == 0.5
        assert _get(hardware, path) == 0.26

    for path in VELOCITY_LIST_PATHS:
        *parent_path, idx = path
        sim_value = _get(sim, parent_path)[idx]
        hardware_value = _get(hardware, parent_path)[idx]
        assert abs(sim_value) == 0.5
        assert abs(hardware_value) == 0.26

    # Blank out the documented diffs and the two documents should be identical: no other
    # value moved when the hardware variant was written.
    sim_doc = _load(SIM_PARAMS_PATH)
    hardware_doc = _load(HARDWARE_PARAMS_PATH)
    sim_doc["controller_server"]["ros__parameters"]["FollowPath"]["max_vel_x"] = None
    sim_doc["controller_server"]["ros__parameters"]["FollowPath"]["max_speed_xy"] = None
    hardware_doc["controller_server"]["ros__parameters"]["FollowPath"]["max_vel_x"] = None
    hardware_doc["controller_server"]["ros__parameters"]["FollowPath"]["max_speed_xy"] = None
    sim_doc["velocity_smoother"]["ros__parameters"]["max_velocity"][0] = None
    sim_doc["velocity_smoother"]["ros__parameters"]["min_velocity"][0] = None
    hardware_doc["velocity_smoother"]["ros__parameters"]["max_velocity"][0] = None
    hardware_doc["velocity_smoother"]["ros__parameters"]["min_velocity"][0] = None

    assert sim_doc == hardware_doc
