"""Subscription-only adapter. No publisher, action client or controller switch client.

The audited existing controller has no independent command watchdog. Consequently
real execute is deliberately rejected at configuration time. Dry-run maps targets
without constructing any writable ROS endpoint.
"""
import base64
import copy
import os
from pathlib import Path
import struct
import threading
import time

from ..kinematics import UrdfFK
from ..protocol import PlatformError, require
from .ros_mapping import named_state


def image_size(data):
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        return (*struct.unpack('!II', data[16:24]), "png")
    if data[:2] == b'\xff\xd8':
        i = 2
        while i+4 <= len(data):
            if data[i] != 255:
                i += 1
                continue
            marker = data[i+1]
            i += 2
            if marker in (0xd8, 0xd9, 0x01) or 0xd0 <= marker <= 0xd7:
                continue
            size = int.from_bytes(data[i:i+2], "big")
            if marker in (0xc0, 0xc1, 0xc2) and i+7 <= len(data):
                h, w = struct.unpack('!HH', data[i+3:i+7])
                return w, h, "jpeg"
            if size < 2:
                break
            i += size
    raise ValueError("Expected an encoded PNG or JPEG image")


class ROS2Backend:
    executable = hardware_verified = False
    writes = 0

    def __init__(self, cfg):
        require(cfg["permission"] in ("read_only", "dry_run"), "EXECUTION_NOT_VERIFIED", "ROS writes are unavailable")
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import JointState, CompressedImage
        self.cfg, self.rclpy = cfg, rclpy
        require(os.environ.get("ROS_DISTRO") == "humble", "CONFIGURATION_ERROR", "Source the verified ROS 2 Humble environment")
        require(os.environ.get("ROS_DOMAIN_ID", "0") == str(cfg["ros"]["domain_id"]),
                "CONFIGURATION_ERROR", "ROS_DOMAIN_ID differs from configuration")
        require(os.environ.get("RMW_IMPLEMENTATION") == cfg["ros"]["middleware"],
                "CONFIGURATION_ERROR", "RMW_IMPLEMENTATION differs from configuration")
        self.lock = threading.Lock()
        self.samples = {}
        self.errors = {}
        self.context = Context()
        rclpy.init(context=self.context)
        self.node = rclpy.create_node("franka_platform_reader", context=self.context,
                                     namespace=cfg["ros"].get("namespace", ""),
                                     enable_rosout=False, start_parameter_services=False)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.executor.add_node(self.node)
        ros = cfg["ros"]
        self.fk = None
        if ros.get("robot_description_file"):
            self.fk = UrdfFK(Path(ros["robot_description_file"]).expanduser(),
                             cfg["base_frame_id"], cfg["tool_frame_id"], cfg["joint_names"])
        self.subscriptions = [self.node.create_subscription(JointState, ros["joint_state_topic"],
                                 self._callback("robot"), qos_profile_sensor_data),
                              self.node.create_subscription(JointState, ros["gripper_state_topic"],
                                 self._callback("gripper"), qos_profile_sensor_data)]
        if cfg["observation_profile"] == "dual_camera":
            for cam in cfg["cameras"]:
                self.subscriptions.append(self.node.create_subscription(CompressedImage, cam["topic"],
                                            self._callback(cam["name"]), qos_profile_sensor_data))
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()

    def _callback(self, name):
        def receive(msg):
            arrival = time.monotonic()
            stamp = msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9
            lag = self.node.get_clock().now().nanoseconds*1e-9-stamp
            try:
                if name in ("robot", "gripper"):
                    order = self.cfg["joint_names"] if name == "robot" else self.cfg["ros"]["finger_joint_names"]
                    data = named_state(list(msg.name), list(msg.position),
                                       list(msg.velocity) if name == "robot" else None, order)
                else:
                    camera = next(c for c in self.cfg["cameras"] if c["name"] == name)
                    require(msg.header.frame_id == camera["frame"], "FRAME_MISMATCH", "Camera optical frame differs from configuration")
                    content = bytes(msg.data)
                    w, h, encoding = image_size(content)
                    data = {"data_base64": base64.b64encode(content).decode(), "width": w, "height": h,
                            "encoding": encoding, "frame": msg.header.frame_id, "source": "ros_compressed_image"}
                with self.lock:
                    self.samples[name] = {"data": data, "stamp": stamp, "arrival": arrival, "lag": lag}
                    self.errors.pop(name, None)
            except (PlatformError, ValueError, IndexError, struct.error) as exc:
                with self.lock:
                    self.errors[name] = str(exc)
                    self.samples.pop(name, None)
        return receive

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            samples, errors = copy.deepcopy(self.samples), dict(self.errors)
        def age(sample):
            if not sample or sample["lag"] < -.1:
                return None
            return now-sample["arrival"]+max(0., sample["lag"])
        robot, grip = samples.get("robot"), samples.get("gripper")
        q = robot["data"]["positions"] if robot else None
        pose = {"position_m": None, "quaternion_xyzw": None, "available": False, "source": "URDF FK unavailable"}
        if q is not None and self.fk:
            try:
                pose = {**self.fk.pose(q), "available": True, "source": "FK from configured URDF and measured named joints"}
            except PlatformError:
                errors["fk"] = "Invalid measured joint values"
        s = {"joint_names": self.cfg["joint_names"], "positions_rad": q,
             "velocities_rad_s": robot["data"]["velocities"] if robot else None, "tcp_pose": pose,
             "gripper": {"width_m": sum(grip["data"]["positions"]) if grip else None,
                         "available": grip is not None, "timestamp_s": grip["stamp"] if grip else None,
                         "age_s": age(grip), "clock": "ROS header stamp", "driver_status": "state_only; action readiness unverified"},
             "robot_status": {"connected": robot is not None, "fault": errors or None,
                              "source": "joint_state only; FCI/controller health unverified"},
             "source_timestamps": {k: {"value_s": v["stamp"], "clock": "ROS header stamp",
                                       "arrival_monotonic_s": v["arrival"], "arrival_lag_s": v["lag"]} for k, v in samples.items()},
             "cameras": [], "freshness": {"state_age_s": age(robot), "pair_skew_s": None,
             "pairing_strategy": "latest received samples; ROS header timestamp skew; no hardware synchronization"}}
        timestamps = [robot["stamp"]] if robot else []
        if self.cfg["observation_profile"] == "dual_camera":
            for cam in self.cfg["cameras"]:
                sample = samples.get(cam["name"])
                entry = {"name": cam["name"], "available": sample is not None, "age_s": age(sample),
                         "timestamp_s": sample["stamp"] if sample else None, "clock": "ROS header stamp",
                         "data_base64": None, "frame": cam["frame"], "source": "ros_compressed_image"}
                if sample:
                    entry.update(sample["data"])
                    timestamps.append(sample["stamp"])
                s["cameras"].append(entry)
        if len(timestamps) == (3 if self.cfg["observation_profile"] == "dual_camera" else 1):
            s["freshness"]["pair_skew_s"] = max(timestamps)-min(timestamps)
        return s

    def submit(self, target):
        raise PlatformError("EXECUTION_NOT_VERIFIED", "No actuator endpoints exist in this ROS backend")

    def switch(self, mode):
        raise PlatformError("EXECUTION_NOT_VERIFIED", "No controller switch client exists in this ROS backend")

    def stop(self):
        # Subscription-only operation: no hold command, stop service, or gripper goal.
        pass

    def close(self):
        self.executor.shutdown(timeout_sec=2)
        self.thread.join(timeout=2)
        self.node.destroy_node()
        self.rclpy.shutdown(context=self.context)
