"""Deterministic target acknowledgement, deliberately not a physics simulator."""
import base64
import copy
import struct
import time
import zlib


def png():
    def chunk(kind, data):
        return struct.pack('!I', len(data))+kind+data+struct.pack('!I', zlib.crc32(kind+data))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('!2I5B', 2, 2, 8, 2, 0, 0, 0))+
            chunk(b'IDAT', zlib.compress(b'\0\xff\0\0\0\xff\0\0\0\0\xff\xff\xff\xff'))+chunk(b'IEND', b''))


class MockBackend:
    executable = True
    hardware_verified = False

    def __init__(self, cfg, clock=time.monotonic):
        self.cfg, self.clock = cfg, clock
        self.writes = self.stop_count = 0
        self.mode = None
        self.pending = None
        self.freeze_feedback = self.fail_switch = False
        self.connected, self.fault = True, None
        self.camera_age = self.camera_skew = self.state_age = 0.0
        self.missing_camera = False
        self.state = {"joint_names": cfg["joint_names"], "positions_rad": [0., -.5, 0., -1.5, 0., 1.5, 0.],
                      "velocities_rad_s": [0.]*7,
                      "tcp_pose": {"position_m": [.4, 0., .4], "quaternion_xyzw": [0., 0., 0., 1.]},
                      "gripper": {"width_m": .04, "available": True, "driver_status": "mock"}}

    def snapshot(self):
        now = self.clock()
        if self.pending and now >= self.pending[0] and not self.freeze_feedback:
            target = self.pending[1]
            if target["type"] == "joint_absolute":
                self.state["positions_rad"] = target["positions_rad"][:]
            elif target["type"] == "gripper_width":
                self.state["gripper"]["width_m"] = target["width_m"]
            else:
                self.state["tcp_pose"] = copy.deepcopy(target["tcp_pose"])
            self.pending = None
        s = copy.deepcopy(self.state)
        s["robot_status"] = {"connected": self.connected, "fault": self.fault, "source": "mock"}
        s["source_timestamps"] = {"robot": {"value_s": now-self.state_age, "clock": "server_monotonic_mock"}}
        s["gripper"].update(timestamp_s=now, clock="server_monotonic_mock", age_s=0.)
        s["freshness"] = {"state_age_s": self.state_age, "pair_skew_s": self.camera_skew,
                          "pairing_strategy": "latest_by_receive_time; mock timestamps"}
        s["cameras"] = []
        if self.cfg["observation_profile"] == "dual_camera":
            for i, c in enumerate(self.cfg["cameras"]):
                age = self.camera_age + (self.camera_skew if i else 0)
                s["cameras"].append({"name": c["name"], "source": "mock", "available": not self.missing_camera,
                    "encoding": "png", "width": 2, "height": 2, "frame": c["frame"],
                    "timestamp_s": now-age, "clock": "server_monotonic_mock", "age_s": age,
                    "data_base64": base64.b64encode(png()).decode() if not self.missing_camera else None})
        return s

    def submit(self, target):
        self.writes += 1
        self.pending = (self.clock()+self.cfg.get("mock_feedback_delay_s", .08), copy.deepcopy(target))

    def switch(self, mode):
        if self.fail_switch:
            return False
        self.mode = mode
        return True

    def stop(self):
        self.stop_count += 1
        self.pending = None

    def close(self):
        self.stop()
