"""Serialized control state machine. All timestamps used for expiry are server-local."""
import copy
import time
import uuid
from collections import OrderedDict

from .protocol import ACTION_MODES, PlatformError, TERMINAL, dumps, finite, require, vector
from .transforms import angle, quaternion
from .validation import convert, envelope


class Platform:
    def __init__(self, cfg, backend, clock=time.monotonic, log=None):
        self.cfg, self.backend, self.clock = cfg, backend, clock
        self.log = log or (lambda event: None)
        self.epoch = 0
        self.mode = None
        self.owner = self.session = None
        self.lease_deadline = 0
        self.fault = None
        self.observations = OrderedDict()
        self.commands = OrderedDict()
        self.active = None

    def _log(self, event, **data):
        self.log({"schema_version": 1, "event": event, "server_monotonic_s": self.clock(),
                  "session_id": self.session, "control_epoch": self.epoch, "control_mode": self.mode,
                  "backend": self.cfg["backend"], "permission": self.cfg["permission"], **data})

    def _stop_backend(self):
        if self.cfg["permission"] == "execute":
            self.backend.stop()

    def _abort(self, reason):
        if self.active:
            command = self.commands[self.active]
            command.update(state="aborted", error_code=reason)
            self._log("command_aborted", **self.public_command(command))
            self.active = None

    def _invalidate(self, reason, fault=False):
        self._abort(reason)
        self._stop_backend()
        self.epoch += 1
        self.observations.clear()
        self.mode = None
        if fault:
            self.fault = reason
        self._log("invalidated", error_code=reason)

    def disconnect(self, connection):
        if self.owner == connection:
            self._invalidate("CLIENT_DISCONNECTED")
            self.owner = self.session = None

    def _owned(self, connection, session_id):
        require(connection == self.owner and session_id == self.session and self.session is not None,
                "CONTROL_NOT_OWNED", "Acquire the current connection's writer session first")

    def capabilities(self):
        return {"schema_version": 1, "action_types": {k: {"protocol_implemented": True,
                "backend_executable": self.backend.executable and self.cfg["permission"] == "execute",
                "hardware_verified": self.backend.hardware_verified} for k in ACTION_MODES},
                "backend": self.cfg["backend"], "permission": self.cfg["permission"],
                "control_modes": ["cartesian", "joint"], "current_mode": self.mode,
                "joint_names": self.cfg["joint_names"], "base_frame_id": self.cfg["base_frame_id"],
                "tool_frame_id": self.cfg["tool_frame_id"], "units": {"position": "m", "angle": "rad", "time": "s"},
                "quaternion_order": "xyzw", "quaternion_norm_tolerance": 1e-3,
                "delta_rotation": "q_delta_base * q_reference", "observation_profile": self.cfg["observation_profile"],
                "validity_limits": copy.deepcopy(self.cfg["timing"]),
                "camera_names": [c["name"] for c in self.cfg.get("cameras", [])],
                "gripper": {"independent": True, "width_semantics": "total finger opening in metres"},
                "completion_feedback": self.backend.executable, "real_execute_blocker":
                None if self.cfg["backend"] == "mock" else "Independent watchdog and stop/switch hardware acceptance pending"}

    def _state_problem(self, s, gripper=False, elapsed_s=0.):
        if not s["robot_status"]["connected"] or s["robot_status"]["fault"]:
            return "ROBOT_NOT_READY"
        try:
            require(s["joint_names"] == self.cfg["joint_names"], "ROBOT_NOT_READY", "Joint names mismatch")
            vector(s["positions_rad"], 7, "state positions")
            vector(s["velocities_rad_s"], 7, "state velocities")
            vector(s["tcp_pose"]["position_m"], 3, "state position")
            quaternion(s["tcp_pose"]["quaternion_xyzw"])
        except (PlatformError, KeyError, TypeError):
            return "ROBOT_NOT_READY"
        age = s["freshness"].get("state_age_s")
        if not finite(age) or not 0 <= age+elapsed_s <= self.cfg["timing"]["state_max_age_s"]:
            return "STALE_STATE"
        if gripper:
            g = s["gripper"]
            if not g["available"] or not finite(g.get("width_m")):
                return "ROBOT_NOT_READY"
            if not finite(g.get("age_s")) or not 0 <= g["age_s"]+elapsed_s <= self.cfg["timing"]["state_max_age_s"]:
                return "STALE_STATE"
        if self.cfg["observation_profile"] == "dual_camera":
            cameras = s["cameras"]
            if len(cameras) != 2 or any(not c["available"] or not c.get("data_base64") for c in cameras):
                return "CAMERA_UNAVAILABLE"
            if any(not finite(c.get("age_s")) or not 0 <= c["age_s"]+elapsed_s <= self.cfg["timing"]["camera_max_age_s"] for c in cameras):
                return "STALE_CAMERA"
            skew = s["freshness"].get("pair_skew_s")
            if not finite(skew) or skew > self.cfg["timing"]["pair_max_skew_s"]:
                return "SENSOR_SKEW"
        return None

    def status(self):
        state = self.backend.snapshot()
        problem = self._state_problem(state)
        return {"schema_version": 1, "control_epoch": self.epoch, "control_mode": self.mode,
                "writer_present": self.owner is not None, "fault": self.fault,
                "backend": self.cfg["backend"], "permission": self.cfg["permission"],
                "robot_status": state["robot_status"], "observation_problem": problem,
                "can_accept_actions": self.owner is not None and self.mode is not None
                and self.cfg["permission"] != "read_only" and not (self.fault or problem),
                "actuator_write_count": self.backend.writes}

    def observation(self):
        s = copy.deepcopy(self.backend.snapshot())
        now = self.clock()
        oid = uuid.uuid4().hex
        s.update(schema_version=1, observation_id=oid, control_epoch=self.epoch,
                 server_monotonic_s=now, server_clock="monotonic; not comparable between hosts")
        s["tcp_pose"].update(base_frame=self.cfg["base_frame_id"], tool_frame=self.cfg["tool_frame_id"])
        s["robot_status"].update(control_mode=self.mode, can_accept_actions=self.status()["can_accept_actions"])
        s["freshness"]["action_blocker"] = self._state_problem(s)
        s["freshness"]["camera_max_age_s"] = self.cfg["timing"]["camera_max_age_s"]
        self.observations[oid] = {"time": now, "epoch": self.epoch, "state": copy.deepcopy(s), "consumed": False}
        while len(self.observations) > 256:
            self.observations.popitem(last=False)
        return s

    def acquire(self, connection):
        require(self.cfg["permission"] != "read_only", "READ_ONLY", "Read-only service has no writer path")
        require(self.owner is None, "CONTROL_NOT_OWNED", "A writer session is already active")
        self.owner, self.session = connection, uuid.uuid4().hex
        self.fault = None
        self.epoch += 1
        self.mode = None
        self.observations.clear()
        self.commands.clear()
        self.lease_deadline = self.clock()+self.cfg["timing"]["lease_timeout_s"]
        self._log("control_acquired")
        return {"session_id": self.session, "control_epoch": self.epoch,
                "lease_timeout_s": self.cfg["timing"]["lease_timeout_s"]}

    def heartbeat(self, connection, session_id):
        self._owned(connection, session_id)
        self.lease_deadline = self.clock()+self.cfg["timing"]["lease_timeout_s"]
        return {"control_epoch": self.epoch}

    def set_mode(self, connection, session_id, mode):
        self._owned(connection, session_id)
        require(mode in ("cartesian", "joint"), "INVALID_ACTION", "Unknown control mode")
        require(not self.fault, "ROBOT_NOT_READY", "Release and reacquire after a fault")
        self._invalidate("CONTROL_MODE_CHANGED")
        # dry_run modes are virtual; there are no controller-manager writes.
        if self.cfg["permission"] == "execute" and not self.backend.switch(mode):
            self.fault = "CONTROLLER_SWITCH_FAILED"
            self._log("switch_failed", error_code=self.fault)
            raise PlatformError(self.fault, "Controller switch failed; no commands will be sent")
        self.mode = mode
        self._log("mode_changed")
        return {"control_epoch": self.epoch, "control_mode": self.mode}

    def stop(self, connection, session_id):
        self._owned(connection, session_id)
        self._invalidate("STOPPED")
        return self.status()

    def release(self, connection, session_id):
        self._owned(connection, session_id)
        self._invalidate("CONTROL_RELEASED")
        self.owner = self.session = None
        return {"released": True, "control_epoch": self.epoch}

    @staticmethod
    def public_command(command):
        return {k: copy.deepcopy(v) for k, v in command.items() if not k.startswith("_")}

    def command_status(self, request_id):
        require(request_id in self.commands, "UNKNOWN_COMMAND", "Request not retained in the current writer session")
        return self.public_command(self.commands[request_id])

    def send_action(self, connection, action):
        envelope(action)
        self._owned(connection, action["session_id"])
        require(action["control_epoch"] == self.epoch, "STALE_EPOCH", "Control epoch changed; obtain a new observation")
        fingerprint = dumps(action)
        rid = action["request_id"]
        if rid in self.commands:
            require(self.commands[rid]["_fingerprint"] == fingerprint, "REQUEST_ID_CONFLICT", "Request ID reused with different content")
            return self.command_status(rid)
        require(len(self.commands) < 4096, "SESSION_CAPACITY", "Release and reacquire to start a new session")
        try:
            require(not self.fault, "ROBOT_NOT_READY", "Fault requires explicit release and reacquire")
            expected = ACTION_MODES[action["type"]]
            require(self.mode is not None and (expected is None or expected == self.mode),
                    "CONTROL_MODE_MISMATCH", "Explicitly select the action's control mode first")
            ref = self.observations.get(action["observation_id"])
            require(ref is not None and ref["epoch"] == self.epoch and
                    0 <= self.clock()-ref["time"] <= self.cfg["timing"]["observation_max_age_s"],
                    "STALE_OBSERVATION", "Observation is unknown, expired or from a previous control epoch")
            require(not (action["type"] == "cartesian_delta" and ref["consumed"]),
                    "DUPLICATE_REFERENCE", "Reference observation already consumed by a relative action")
            problem = self._state_problem(ref["state"], action["type"] == "gripper_width", self.clock()-ref["time"])
            require(problem is None, problem or "ROBOT_NOT_READY", "Referenced sensor observation is invalid")
            current = self.backend.snapshot()
            problem = self._state_problem(current, action["type"] == "gripper_width")
            require(problem is None, problem or "ROBOT_NOT_READY", "Latest measured state or sensor data is invalid")
            target = convert(action, ref["state"], current, self.cfg)
            if self.cfg["backend"] == "real":
                from .backends.ros_mapping import target_message
                target["backend_mapping"] = target_message(target, self.cfg)
            require(self.active is None, "COMMAND_IN_PROGRESS", "v1 accepts one target at a time; stop or await completion")
        except PlatformError as exc:
            command = {"request_id": rid, "session_id": self.session, "observation_id": action["observation_id"],
                       "control_epoch": self.epoch, "type": action["type"], "state": "rejected",
                       "error_code": exc.code, "message": str(exc), "_fingerprint": fingerprint}
            self.commands[rid] = command
            self._log("command_rejected", raw_request=action, **self.public_command(command))
            raise
        command = {"request_id": rid, "session_id": self.session, "observation_id": action["observation_id"],
                   "control_epoch": self.epoch, "type": action["type"], "state": "validated",
                   "target": target, "error_code": None, "_fingerprint": fingerprint,
                   "_deadline": self.clock()+self.cfg["timing"]["command_timeout_s"],
                   "_start": self.clock(), "_executing_logged": False}
        self.commands[rid] = command
        if action["type"] == "cartesian_delta":
            ref["consumed"] = True
        self._log("command_validated", raw_request=action, **self.public_command(command))
        if self.cfg["permission"] == "execute":
            try:
                self.backend.submit(target)
            except Exception:
                command.update(state="aborted", error_code="BACKEND_ERROR")
                self._invalidate("BACKEND_ERROR", fault=True)
                raise PlatformError("BACKEND_ERROR", "Backend submission failed")
            command["state"] = "accepted"
            self.active = rid
            self._log("command_accepted", **self.public_command(command))
        return self.public_command(command)

    def tick(self):
        now = self.clock()
        if self.owner is not None and now >= self.lease_deadline:
            self._invalidate("LEASE_EXPIRED", fault=True)
            self.owner = self.session = None
        if not self.active:
            return
        cmd = self.commands[self.active]
        s = self.backend.snapshot()
        problem = self._state_problem(s, cmd["type"] == "gripper_width")
        if problem:
            self._invalidate(problem, fault=True)
            return
        if now >= cmd["_deadline"]:
            self._invalidate("COMMAND_TIMEOUT", fault=True)
            return
        cmd["state"] = "executing"
        if not cmd["_executing_logged"]:
            self._log("command_executing", **self.public_command(cmd))
            cmd["_executing_logged"] = True
        target, t = cmd["target"], self.cfg["timing"]
        if target["type"] == "joint_absolute":
            done = max(abs(a-b) for a, b in zip(target["positions_rad"], s["positions_rad"])) <= t["joint_tolerance_rad"]
        elif target["type"] == "gripper_width":
            done = abs(target["width_m"]-s["gripper"]["width_m"]) <= t["gripper_tolerance_m"]
        else:
            import math
            done = (math.dist(target["tcp_pose"]["position_m"], s["tcp_pose"]["position_m"]) <= t["position_tolerance_m"]
                    and angle(target["tcp_pose"]["quaternion_xyzw"], s["tcp_pose"]["quaternion_xyzw"]) <= t["rotation_tolerance_rad"])
        if done:
            cmd["state"] = "completed"
            cmd["feedback"] = {"positions_rad": s["positions_rad"], "tcp_pose": s["tcp_pose"], "gripper": s["gripper"]}
            self.active = None
            self._log("command_completed", **self.public_command(cmd))

    def close(self):
        self._invalidate("SERVER_CLOSED")
        self.backend.close()
