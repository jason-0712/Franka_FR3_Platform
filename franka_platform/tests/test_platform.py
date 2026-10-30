import asyncio
import base64
import copy
import math
from pathlib import Path
import tempfile
import unittest

from franka_platform.backends.mock import MockBackend
from franka_platform.backends.ros_mapping import named_state, target_message
from franka_platform.client import Client
from franka_platform.config import load, validate, with_permission
from franka_platform.core import Platform
from franka_platform.kinematics import UrdfFK
from franka_platform.protocol import PlatformError, loads
from franka_platform.server import Service
from franka_platform.transforms import controller_pose, delta_pose, multiply, quaternion, rotate, tool_pose

CONFIG = Path(__file__).resolve().parents[1]/"configs/mock.yaml"


class Clock:
    now = 100.
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += seconds


class Semantics(unittest.TestCase):
    def setUp(self):
        self.cfg = with_permission(load(CONFIG), "execute")
        self.clock = Clock()
        self.backend = MockBackend(self.cfg, self.clock)
        self.core = Platform(self.cfg, self.backend, self.clock)
        self.session = self.core.acquire("writer")["session_id"]
        self.core.set_mode("writer", self.session, "cartesian")

    def action(self, kind="cartesian_delta", payload=None, observation=None, rid="request-1"):
        observation = observation or self.core.observation()
        return {"schema_version": 1, "request_id": rid, "session_id": self.session,
                "control_epoch": self.core.epoch, "observation_id": observation["observation_id"],
                "type": kind, "payload": payload or {"frame": "base", "tool_frame": "fr3_hand_tcp",
                "translation_m": [.005, 0, 0], "delta_quaternion_xyzw": [0, 0, 0, 1]}}

    def error(self, code, fn, *args):
        with self.assertRaises(PlatformError) as ctx:
            fn(*args)
        self.assertEqual(ctx.exception.code, code)

    def test_noncommutative_base_rotation_preserves_position(self):
        h = math.sqrt(.5)
        ref = {"position_m": [.4, .2, .3], "quaternion_xyzw": [h, 0, 0, h]}
        delta = [0, h, 0, h]
        out = delta_pose(ref, [0, .01, 0], delta)
        self.assertEqual(out["position_m"], [.4, .21000000000000002, .3])
        # Ry(90)*Rx(90): local Y maps to world X. Reversing multiplication maps it to Z.
        for actual, expected in zip(rotate(out["quaternion_xyzw"], [0, 1, 0]), [1, 0, 0]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(delta_pose(ref, [0, 0, 0], [0, 0, 0, 1]), ref)

    def test_offset_tcp_mapping_and_orientation(self):
        h = math.sqrt(.5)
        tcp = {"position_m": [.4, .2, .5], "quaternion_xyzw": [0, 0, h, h]}
        transform = {"position_m": [.1, 0, 0], "quaternion_xyzw": [0, 0, 0, 1]}
        mapped = controller_pose(tcp, transform)
        self.assertAlmostEqual(mapped["position_m"][0], .4)
        self.assertAlmostEqual(mapped["position_m"][1], .1)
        back = tool_pose(mapped, transform)
        for a, b in zip(back["position_m"], tcp["position_m"]):
            self.assertAlmostEqual(a, b)
        # Nonzero fixed rotation as well as offset.
        transform["quaternion_xyzw"] = [h, 0, 0, h]
        mapped = controller_pose(tcp, transform)
        back = tool_pose(mapped, transform)
        for a, b in zip(back["quaternion_xyzw"], tcp["quaternion_xyzw"]):
            self.assertAlmostEqual(a, b)

    def test_specified_reference_latest_state_limits_and_no_accumulation(self):
        obs = self.core.observation()
        self.backend.state["tcp_pose"]["position_m"][0] += .003
        action = self.action(observation=obs)
        cmd = self.core.send_action("writer", action)
        self.assertAlmostEqual(cmd["target"]["tcp_pose"]["position_m"][0], .405)
        self.assertEqual(self.core.send_action("writer", action)["state"], "accepted")
        self.assertEqual(self.backend.writes, 1)
        self.clock.advance(.1)
        self.core.tick()
        self.assertEqual(self.core.send_action("writer", action)["state"], "completed")
        self.assertEqual(self.backend.writes, 1)
        action["request_id"] = "different-id"
        self.error("DUPLICATE_REFERENCE", self.core.send_action, "writer", action)
        fresh = self.core.observation()
        self.backend.state["tcp_pose"]["position_m"][0] += .1
        self.error("LIMIT_EXCEEDED", self.core.send_action, "writer", self.action(observation=fresh, rid="far"))

    def test_request_id_payload_conflict(self):
        action = self.action()
        self.core.send_action("writer", action)
        action["payload"]["translation_m"][0] = .006
        self.error("REQUEST_ID_CONFLICT", self.core.send_action, "writer", action)

    def test_joint_order_dimensions_limits_and_ros_mapping(self):
        self.core.set_mode("writer", self.session, "joint")
        p = {"joint_names": self.cfg["joint_names"][:], "positions_rad": [0, -.5, 0, -1.5, 0, 1.5, 0]}
        p["positions_rad"][0] = .01
        command = self.core.send_action("writer", self.action("joint_absolute", p))
        message = target_message(command["target"], self.cfg)
        self.assertEqual(message["message_type"], "sensor_msgs/msg/JointState")
        self.assertEqual(message["velocity"], [0.]*7)
        self.assertEqual(message["position"], p["positions_rad"])
        self.core.stop("writer", self.session)
        self.core.set_mode("writer", self.session, "joint")
        p["joint_names"].reverse()
        self.error("INVALID_ACTION", self.core.send_action, "writer", self.action("joint_absolute", p, rid="order"))
        p["joint_names"].reverse()
        p["positions_rad"] = [0]*6
        self.error("INVALID_ACTION", self.core.send_action, "writer", self.action("joint_absolute", p, rid="size"))
        p["positions_rad"] = [0]*7  # joint4/joint6 violate the actual non-symmetric shape of the bounds
        self.error("LIMIT_EXCEEDED", self.core.send_action, "writer", self.action("joint_absolute", p, rid="limit"))

    def test_absolute_pose_ros_mapping(self):
        self.cfg["controller_to_tool"]["position_m"] = [.1, 0, 0]
        p = {"frame": "base", "tool_frame": "fr3_hand_tcp", "position_m": [.405, 0, .4], "quaternion_xyzw": [0, 0, 0, 1]}
        cmd = self.core.send_action("writer", self.action("cartesian_absolute", p))
        message = target_message(cmd["target"], self.cfg)
        self.assertEqual(message["frame_id"], "base")
        self.assertAlmostEqual(message["pose"]["position_m"][0], .305)
        self.assertAlmostEqual(self.backend.pending[1]["tcp_pose"]["position_m"][0], .405)

    def test_ownership_mode_epoch_expiry_and_switch_failure(self):
        action = self.action()
        self.error("CONTROL_NOT_OWNED", self.core.send_action, "reader", action)
        self.error("CONTROL_NOT_OWNED", self.core.acquire, "other")
        self.clock.advance(.6)
        self.error("STALE_OBSERVATION", self.core.send_action, "writer", action)
        old = self.action(rid="old-epoch")
        self.core.set_mode("writer", self.session, "joint")
        self.error("STALE_EPOCH", self.core.send_action, "writer", old)
        self.error("CONTROL_MODE_MISMATCH", self.core.send_action, "writer", self.action(rid="wrong-mode"))
        self.backend.fail_switch = True
        self.error("CONTROLLER_SWITCH_FAILED", self.core.set_mode, "writer", self.session, "cartesian")
        self.assertFalse(self.core.status()["can_accept_actions"])
        self.assertEqual(self.backend.writes, 0)

    def test_feedback_timeout_and_disconnect_abort_no_replay(self):
        self.backend.freeze_feedback = True
        cmd = self.core.send_action("writer", self.action())
        self.assertEqual(cmd["state"], "accepted")
        self.core.tick()
        self.assertEqual(self.core.command_status(cmd["request_id"])["state"], "executing")
        self.clock.advance(1.1)
        self.core.tick()
        result = self.core.command_status(cmd["request_id"])
        self.assertEqual((result["state"], result["error_code"]), ("aborted", "COMMAND_TIMEOUT"))
        self.assertIsNone(self.backend.pending)
        self.core.disconnect("writer")
        self.assertIsNone(self.core.owner)
        self.assertEqual(self.backend.writes, 1)
        self.error("CONTROL_NOT_OWNED", self.core.send_action, "writer", self.action(rid="replay"))

    def test_independent_gripper_and_no_implicit_change(self):
        self.assertEqual(self.backend.state["gripper"]["width_m"], .04)
        action = self.action("gripper_width", {"width_m": .03})
        cmd = self.core.send_action("writer", action)
        mapping = target_message(cmd["target"], self.cfg)
        self.assertEqual(mapping["action"], "/franka_gripper/move")
        self.assertEqual(mapping["width"], .03)
        self.clock.advance(.1)
        self.core.tick()
        self.assertEqual(self.core.command_status(cmd["request_id"])["state"], "completed")

    def test_invalid_messages_and_quaternion_tolerance(self):
        for p in ([0, 0, 0, 0], [0, 0, 0, 2], [0, float('inf'), 0, 1]):
            self.error("INVALID_ACTION", quaternion, p)
        self.assertEqual(quaternion([0, 0, 0, 1.0005]), [0, 0, 0, 1])
        for raw in ('{"a":NaN}', '{"a":1,"a":2}', '[1e999]', '{'):
            self.error("INVALID_ACTION", loads, raw)
        a = self.action()
        a["type"] = "velocity"
        self.error("UNSUPPORTED_ACTION", self.core.send_action, "writer", a)
        a = self.action(rid="nan")
        a["payload"]["translation_m"][0] = float('nan')
        # Direct Python callers are held to the same finite JSON restriction.
        self.error("INVALID_ACTION", self.core.send_action, "writer", a)
        a = self.action(rid="tool-frame")
        a["payload"]["frame"] = "fr3_hand_tcp"
        self.error("FRAME_MISMATCH", self.core.send_action, "writer", a)
        a = self.action(rid="unknown-field")
        a["payload"]["units"] = "normalized"
        self.error("INVALID_ACTION", self.core.send_action, "writer", a)

    def test_camera_missing_stale_skew_and_state_faults_are_distinct(self):
        for attr, value, error in (("missing_camera", True, "CAMERA_UNAVAILABLE"),
                                   ("camera_age", .6, "STALE_CAMERA"),
                                   ("camera_skew", .11, "SENSOR_SKEW"),
                                   ("state_age", .6, "STALE_STATE"),
                                   ("connected", False, "ROBOT_NOT_READY")):
            before = getattr(self.backend, attr)
            setattr(self.backend, attr, value)
            self.assertEqual(self.core.observation()["freshness"]["action_blocker"], error)
            self.error(error, self.core.send_action, "writer", self.action(rid=attr))
            setattr(self.backend, attr, before)

    def test_reference_sensor_age_continues_after_observation_capture(self):
        self.backend.state_age = .4
        obs = self.core.observation()
        self.backend.state_age = 0.
        self.clock.advance(.2)
        self.error("STALE_STATE", self.core.send_action, "writer", self.action(observation=obs))

    def test_read_only_and_dry_run_all_paths_write_zero(self):
        for permission in ("read_only", "dry_run"):
            cfg = with_permission(self.cfg, permission)
            backend = MockBackend(cfg, self.clock)
            core = Platform(cfg, backend, self.clock)
            core.observation()
            if permission == "read_only":
                self.error("READ_ONLY", core.acquire, "writer")
            else:
                session = core.acquire("writer")["session_id"]
                for mode, typ, p in (("cartesian", "cartesian_absolute", {"frame": "base", "tool_frame": "fr3_hand_tcp", "position_m": [.4, 0, .4], "quaternion_xyzw": [0, 0, 0, 1]}),
                    ("cartesian", "cartesian_delta", {"frame": "base", "tool_frame": "fr3_hand_tcp", "translation_m": [0, 0, 0], "delta_quaternion_xyzw": [0, 0, 0, 1]}),
                    ("joint", "joint_absolute", {"joint_names": cfg["joint_names"], "positions_rad": [0, -.5, 0, -1.5, 0, 1.5, 0]}),
                    ("joint", "gripper_width", {"width_m": .03})):
                    core.set_mode("writer", session, mode)
                    a = self.action(typ, p, core.observation(), rid=typ)
                    a.update(session_id=session, control_epoch=core.epoch)
                    self.assertEqual(core.send_action("writer", a)["state"], "validated")
                core.stop("writer", session)
                core.release("writer", session)
            core.close()
            self.assertEqual(backend.writes, 0)
            self.assertEqual(backend.state["gripper"]["width_m"], .04)

    def test_missing_limits_and_real_execute_fail_closed(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["limits"]["max_joint_step_rad"] = None
        self.error("CONFIGURATION_ERROR", validate, cfg)
        cfg = load(CONFIG.parent/"robot.example.yaml")
        self.error("EXECUTION_NOT_VERIFIED", with_permission, cfg, "execute")
        self.error("CONFIGURATION_ERROR", with_permission, cfg, "dry_run")

    def test_named_measured_joints_reordered_without_assuming_message_order(self):
        names = ["fr3_joint"+str(i) for i in (1, 3, 6, 7, 2, 4, 5)]
        state = named_state(names, [1, 3, 6, 7, 2, 4, 5], [.1, .3, .6, .7, .2, .4, .5], self.cfg["joint_names"])
        self.assertEqual(state["positions"], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(state["velocities"], [.1, .2, .3, .4, .5, .6, .7])
        self.error("ROBOT_NOT_READY", named_state, names[:-1], [1]*6, [0]*6, self.cfg["joint_names"])
        self.error("ROBOT_NOT_READY", named_state, names, [1]*7, [], self.cfg["joint_names"])

    def test_mode_switch_aborts_active_and_requires_new_observation(self):
        original = self.action()
        self.core.send_action("writer", original)
        self.core.set_mode("writer", self.session, "joint")
        self.assertEqual(self.core.command_status(original["request_id"])["state"], "aborted")
        self.assertIsNone(self.backend.pending)
        self.error("STALE_EPOCH", self.core.send_action, "writer", original)
        self.core.release("writer", self.session)
        self.session = self.core.acquire("writer")["session_id"]
        self.core.set_mode("writer", self.session, "cartesian")
        original["session_id"] = self.session
        original["control_epoch"] = self.core.epoch
        self.error("STALE_OBSERVATION", self.core.send_action, "writer", original)
        self.assertEqual(self.backend.writes, 1)

    def test_urdf_fk_nonzero_origins_and_order_validation(self):
        joints = []
        for i in range(7):
            joints.append(f'<joint name="fr3_joint{i+1}" type="revolute"><parent link="l{i}"/>'
                f'<child link="l{i+1}"/><origin xyz="0.1 0 0" rpy="0 0 0"/><axis xyz="0 0 1"/></joint>')
        joints.append('<joint name="tool" type="fixed"><parent link="l7"/><child link="tcp"/><origin xyz="0 0 .2"/></joint>')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"robot.urdf"
            path.write_text('<robot name="test">'+''.join(joints)+'</robot>')
            fk = UrdfFK(path, "l0", "tcp", self.cfg["joint_names"])
            pose = fk.pose([math.pi/2]+[0.]*6)
            for a, b in zip(pose["position_m"], [.1, .6, .2]):
                self.assertAlmostEqual(a, b)
            self.error("CONFIGURATION_ERROR", UrdfFK, path, "l0", "tcp", list(reversed(self.cfg["joint_names"])))


class Transport(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cfg = with_permission(load(CONFIG), "execute")
        cfg["network"]["port"] = 0
        self.backend = MockBackend(cfg)
        self.platform = Platform(cfg, self.backend)
        self.service = Service(self.platform)
        self.port = await self.service.start()
        self.client = Client(f"ws://127.0.0.1:{self.port}")
        await self.client.connect()

    async def asyncTearDown(self):
        await self.client.close()
        await self.service.close()

    async def complete(self, command):
        self.assertEqual(command["state"], "accepted")
        for _ in range(100):
            state = await self.client.get_command_status(command["request_id"])
            if state["state"] == "completed":
                return state
            await asyncio.sleep(.01)
        self.fail("Mock target did not complete")

    async def test_sdk_three_actions_images_mode_gripper_and_errors(self):
        cap = await self.client.get_capabilities()
        self.assertFalse(cap["action_types"]["joint_absolute"]["hardware_verified"])
        obs = await self.client.get_observation()
        self.assertEqual(len(obs["cameras"]), 2)
        for c in obs["cameras"]:
            self.assertTrue(base64.b64decode(c["data_base64"]).startswith(b'\x89PNG'))
            self.assertEqual(c["source"], "mock")
            self.assertIsInstance(c["timestamp_s"], float)
        await self.client.acquire_control()
        await self.client.set_control_mode("cartesian")
        p = {"frame": "base", "tool_frame": "fr3_hand_tcp", "position_m": [.405, 0, .4], "quaternion_xyzw": [0, 0, 0, 1]}
        a = self.client.action("cartesian_absolute", p, await self.client.get_observation())
        await self.complete(await self.client.send_action(a))
        p = {"frame": "base", "tool_frame": "fr3_hand_tcp", "translation_m": [0, .005, 0], "delta_quaternion_xyzw": [0, 0, 0, 1]}
        a = self.client.action("cartesian_delta", p, await self.client.get_observation())
        await self.complete(await self.client.send_action(a))
        await self.client.send_action(a)
        self.assertEqual(self.backend.writes, 2)
        await self.client.set_control_mode("joint")
        p = {"joint_names": cap["joint_names"], "positions_rad": [.01, -.5, 0, -1.5, 0, 1.5, 0]}
        a = self.client.action("joint_absolute", p, await self.client.get_observation())
        await self.complete(await self.client.send_action(a))
        await self.complete(await self.client.set_gripper(.035))
        bad = self.client.action("cartesian_delta", {}, await self.client.get_observation())
        with self.assertRaises(PlatformError) as ctx:
            await self.client.send_action(bad)
        self.assertEqual(ctx.exception.code, "CONTROL_MODE_MISMATCH")
        await self.client.stop()
        await self.client.release_control()
        self.assertEqual((await self.client.get_status())["actuator_write_count"], 4)

    async def test_reader_cannot_hijack_writer_and_disconnect_stops(self):
        await self.client.acquire_control()
        await self.client.set_control_mode("cartesian")
        self.backend.freeze_feedback = True
        a = self.client.action("cartesian_delta", {"frame": "base", "tool_frame": "fr3_hand_tcp", "translation_m": [.005, 0, 0], "delta_quaternion_xyzw": [0, 0, 0, 1]}, await self.client.get_observation())
        async with Client(f"ws://127.0.0.1:{self.port}") as reader:
            await reader.get_observation()
            with self.assertRaises(PlatformError) as ctx:
                await reader.send_action(a)
            self.assertEqual(ctx.exception.code, "CONTROL_NOT_OWNED")
            await self.client.send_action(a)
            await self.client.close()
            await asyncio.sleep(.04)
            status = await reader.get_command_status(a["request_id"])
            self.assertEqual(status["state"], "aborted")
            self.assertIsNone(self.backend.pending)

    async def test_watchdog_does_not_depend_on_network_requests(self):
        await self.client.acquire_control()
        await self.client.set_control_mode("cartesian")
        await self.client._cancel_heartbeat()
        self.platform.lease_deadline = self.platform.clock()+.03
        await asyncio.sleep(.08)
        self.assertIsNone(self.platform.owner)
        self.assertEqual(self.platform.fault, "LEASE_EXPIRED")


if __name__ == "__main__":
    unittest.main()
