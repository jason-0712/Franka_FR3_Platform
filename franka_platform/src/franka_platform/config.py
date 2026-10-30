import copy
from pathlib import Path
import yaml
from .protocol import finite, require, vector
from .transforms import quaternion


def load(path):
    with open(path, encoding="utf-8") as stream:
        cfg = yaml.safe_load(stream)
    validate(cfg)
    return cfg


def validate(cfg):
    require(isinstance(cfg, dict), "CONFIGURATION_ERROR", "Configuration must be an object")
    require(type(cfg.get("schema_version")) is int and cfg["schema_version"] == 1,
            "CONFIGURATION_ERROR", "schema_version must be integer 1")
    require(cfg.get("backend") in ("mock", "real"), "CONFIGURATION_ERROR", "backend: mock or real")
    require(cfg.get("permission") in ("read_only", "dry_run", "execute"),
            "CONFIGURATION_ERROR", "permission: read_only, dry_run or execute")
    names = cfg.get("joint_names")
    require(isinstance(names, list) and len(names) == 7
            and all(isinstance(n, str) and n for n in names) and len(set(names)) == 7, "CONFIGURATION_ERROR",
            "joint_names must name seven distinct joints in controller order")
    for key in ("base_frame_id", "tool_frame_id"):
        require(isinstance(cfg.get(key), str) and cfg[key], "CONFIGURATION_ERROR", key+" is required")
    require(cfg.get("observation_profile") in ("robot_only", "dual_camera"),
            "CONFIGURATION_ERROR", "observation_profile: robot_only or dual_camera")
    require(isinstance(cfg.get("log_path"), str) and bool(cfg["log_path"]),
            "CONFIGURATION_ERROR", "log_path is required")
    if cfg["backend"] == "real":
        ros = cfg.get("ros", {})
        required_ros = ("joint_state_topic", "gripper_state_topic", "middleware", "finger_joint_names")
        require(isinstance(ros, dict) and all(ros.get(k) for k in required_ros),
                "CONFIGURATION_ERROR", "Required ROS fields: "+", ".join(required_ros))
        require(type(ros.get("domain_id")) is int and 0 <= ros["domain_id"] <= 232,
                "CONFIGURATION_ERROR", "ros.domain_id must be an integer between 0 and 232")
    for k in ("observation_max_age_s", "state_max_age_s", "camera_max_age_s", "pair_max_skew_s",
              "command_timeout_s", "lease_timeout_s", "watchdog_period_s", "position_tolerance_m",
              "rotation_tolerance_rad", "joint_tolerance_rad", "gripper_tolerance_m"):
        v = cfg.get("timing", {}).get(k)
        require(finite(v) and v > 0, "CONFIGURATION_ERROR", "timing."+k+" must be positive")
    require(cfg["timing"]["watchdog_period_s"] < cfg["timing"]["lease_timeout_s"],
            "CONFIGURATION_ERROR", "watchdog period must be less than lease timeout")
    net = cfg.get("network", {})
    require(net.get("host") in ("127.0.0.1", "::1", "localhost"), "CONFIGURATION_ERROR",
            "v1 listens on loopback only; use an SSH tunnel for remote clients")
    require(type(net.get("port")) is int and 0 <= net["port"] <= 65535,
            "CONFIGURATION_ERROR", "Invalid port")
    if cfg["observation_profile"] == "dual_camera":
        cams = cfg.get("cameras", [])
        require(isinstance(cams, list) and len(cams) == 2
                and all(isinstance(c, dict) and isinstance(c.get("name"), str) and c["name"]
                        and isinstance(c.get("frame"), str) and c["frame"] for c in cams)
                and len({c["name"] for c in cams}) == 2,
                "CONFIGURATION_ERROR", "dual_camera requires two distinct cameras")
    if cfg["backend"] == "real":
        require(cfg["permission"] != "execute", "EXECUTION_NOT_VERIFIED",
                "Real execute is disabled: existing controller lacks a verified independent "
                "command watchdog and stop/switch procedure. Complete stage D before enabling writes.")
    if cfg["backend"] == "mock" or cfg["permission"] == "dry_run":
        validate_limits(cfg)
    return cfg


def validate_limits(cfg):
    lim = cfg.get("limits") or {}
    required = ("joint_lower_rad", "joint_upper_rad", "workspace_lower_m", "workspace_upper_m",
                "max_translation_step_m", "max_rotation_step_rad", "max_joint_step_rad",
                "gripper_min_width_m", "gripper_max_width_m", "gripper_speed_m_s")
    missing = [k for k in required if lim.get(k) is None]
    require(not missing, "CONFIGURATION_ERROR", "Missing verified limits: "+", ".join(missing))
    for lo, hi, n in (("joint_lower_rad", "joint_upper_rad", 7),
                      ("workspace_lower_m", "workspace_upper_m", 3)):
        a, b = vector(lim[lo], n, lo), vector(lim[hi], n, hi)
        require(all(x < y for x, y in zip(a, b)), "CONFIGURATION_ERROR", lo+" must be below "+hi)
    for k in required[4:]:
        require(finite(lim[k]) and lim[k] >= 0, "CONFIGURATION_ERROR", "Invalid limit "+k)
    require(lim["gripper_min_width_m"] < lim["gripper_max_width_m"], "CONFIGURATION_ERROR", "Invalid gripper range")
    require(lim["gripper_speed_m_s"] > 0, "CONFIGURATION_ERROR", "Gripper speed must be positive")
    transform = cfg.get("controller_to_tool") or {}
    vector(transform.get("position_m"), 3, "controller_to_tool.position_m")
    quaternion(transform.get("quaternion_xyzw"))
    require(bool(transform.get("source")), "CONFIGURATION_ERROR", "Tool transform source is required")


def with_permission(cfg, permission):
    result = copy.deepcopy(cfg)
    result["permission"] = permission
    return validate(result)
