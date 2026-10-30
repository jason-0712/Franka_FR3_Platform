import math
from .protocol import ACTION_MODES, fields, finite, identifier, require, vector
from .transforms import angle, controller_pose, delta_pose, quaternion


def envelope(action):
    fields(action, ("schema_version", "request_id", "session_id", "control_epoch", "observation_id",
                    "type", "payload"), "action")
    require(type(action["schema_version"]) is int and action["schema_version"] == 1,
            "INVALID_ACTION", "Unsupported schema_version")
    for key in ("request_id", "session_id", "observation_id"):
        identifier(action[key], key)
    require(type(action["control_epoch"]) is int, "INVALID_ACTION", "control_epoch must be an integer")
    require(isinstance(action["type"], str) and action["type"] in ACTION_MODES,
            "UNSUPPORTED_ACTION", "Unsupported action type")


def convert(action, reference, current, cfg):
    typ, p, lim = action["type"], action["payload"], cfg["limits"]
    if typ == "joint_absolute":
        fields(p, ("joint_names", "positions_rad"), "payload")
        require(p["joint_names"] == cfg["joint_names"], "INVALID_ACTION", "Joint order mismatch")
        q = vector(p["positions_rad"], 7, "positions_rad")
        require(all(a <= x <= b for x, a, b in zip(q, lim["joint_lower_rad"], lim["joint_upper_rad"])),
                "LIMIT_EXCEEDED", "Joint position outside verified bounds")
        require(max(abs(a-b) for a, b in zip(q, current["positions_rad"])) <= lim["max_joint_step_rad"],
                "LIMIT_EXCEEDED", "Joint step from latest measured state exceeds limit")
        return {"type": "joint_absolute", "joint_names": cfg["joint_names"],
                "positions_rad": q, "velocities_rad_s": [0.0]*7}
    if typ == "gripper_width":
        fields(p, ("width_m",), "payload")
        width = p["width_m"]
        require(finite(width), "INVALID_ACTION", "width_m must be finite")
        require(lim["gripper_min_width_m"] <= width <= lim["gripper_max_width_m"],
                "LIMIT_EXCEEDED", "Gripper total opening width outside verified limits")
        require(current["gripper"]["available"], "ROBOT_NOT_READY", "Gripper state unavailable")
        return {"type": typ, "width_m": width, "speed_m_s": lim["gripper_speed_m_s"]}
    delta = typ == "cartesian_delta"
    fields(p, ("frame", "tool_frame", "translation_m", "delta_quaternion_xyzw") if delta else
           ("frame", "tool_frame", "position_m", "quaternion_xyzw"), "payload")
    require(p["frame"] == cfg["base_frame_id"] and p["tool_frame"] == cfg["tool_frame_id"],
            "FRAME_MISMATCH", "Only configured base-frame actions and tool frame are supported")
    xyz = vector(p["translation_m" if delta else "position_m"], 3, "translation/position_m")
    q = quaternion(p["delta_quaternion_xyzw" if delta else "quaternion_xyzw"])
    target = delta_pose(reference["tcp_pose"], xyz, q) if delta else {"position_m": xyz, "quaternion_xyzw": q}
    require(all(a <= x <= b for x, a, b in zip(target["position_m"], lim["workspace_lower_m"],
                                             lim["workspace_upper_m"])),
            "LIMIT_EXCEEDED", "TCP position outside verified workspace")
    distance = math.dist(target["position_m"], current["tcp_pose"]["position_m"])
    require(distance <= lim["max_translation_step_m"] and
            angle(target["quaternion_xyzw"], current["tcp_pose"]["quaternion_xyzw"]) <= lim["max_rotation_step_rad"],
            "LIMIT_EXCEEDED", "Cartesian step from latest measured state exceeds limit")
    return {"type": "cartesian_absolute", "tcp_pose": target,
            "controller_pose": controller_pose(target, cfg["controller_to_tool"])}
