"""Audited outgoing message shapes; pure functions, no ROS import or publishing."""
from ..protocol import require, vector


def named_state(names, positions, velocities, expected_names):
    require(len(names) == len(set(names)), "ROBOT_NOT_READY", "Duplicate JointState names")
    require(len(names) == len(positions), "ROBOT_NOT_READY", "JointState position/name sizes differ")
    require(all(n in names for n in expected_names), "ROBOT_NOT_READY", "Required joints missing")
    index = [list(names).index(n) for n in expected_names]
    q = vector([positions[i] for i in index], len(expected_names), "measured joint positions")
    dq = None
    if velocities is not None:
        require(len(velocities) == len(names), "ROBOT_NOT_READY", "Measured joint velocities missing")
        dq = vector([velocities[i] for i in index], len(expected_names), "measured joint velocities")
    return {"positions": q, "velocities": dq}


def target_message(target, cfg):
    if target["type"] == "joint_absolute":
        return {"topic": cfg["ros"]["joint_target_topic"], "message_type": "sensor_msgs/msg/JointState",
                "name": cfg["joint_names"], "position": target["positions_rad"], "velocity": [0.0]*7}
    if target["type"] == "cartesian_absolute":
        return {"topic": cfg["ros"]["pose_target_topic"], "message_type": "geometry_msgs/msg/PoseStamped",
                "frame_id": cfg["base_frame_id"], "pose": target["controller_pose"]}
    return {"action": cfg["ros"]["gripper_move_action"], "message_type": "franka_msgs/action/Move",
            "width": target["width_m"], "speed": target["speed_m_s"]}
