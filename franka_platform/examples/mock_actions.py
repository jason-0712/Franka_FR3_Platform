"""Three deterministic Mock targets, explicit modes, independent gripper, errors."""
import argparse
import asyncio
import json
from franka_platform.client import Client
from franka_platform.protocol import PlatformError, require


async def run(url):
    async with Client(url) as client:
        cap = await client.get_capabilities()
        require(cap["backend"] == "mock", "MOCK_ONLY", "This example runs on Mock only")
        await client.acquire_control()
        async def send(kind, payload):
            action = client.action(kind, payload, await client.get_observation())
            result = await client.send_action(action)
            while result["state"] in ("accepted", "executing"):
                await asyncio.sleep(.02)
                result = await client.get_command_status(result["request_id"])
            print(json.dumps(result))
            require(result["state"] in ("validated", "completed"), "EXAMPLE_FAILED", str(result))
            return action
        await client.set_control_mode("cartesian")
        await send("cartesian_absolute", {"frame": cap["base_frame_id"], "tool_frame": cap["tool_frame_id"],
                   "position_m": [.405, 0, .4], "quaternion_xyzw": [0, 0, 0, 1]})
        action = await send("cartesian_delta", {"frame": cap["base_frame_id"], "tool_frame": cap["tool_frame_id"],
                   "translation_m": [0, .005, 0], "delta_quaternion_xyzw": [0, 0, 0, 1]})
        print("IDEMPOTENT_RETRY", json.dumps(await client.send_action(action)))
        await client.set_control_mode("joint")
        await send("joint_absolute", {"joint_names": cap["joint_names"], "positions_rad": [.01, -.5, 0, -1.5, 0, 1.5, 0]})
        await send("gripper_width", {"width_m": .035})
        try:
            await send("cartesian_absolute", {})
        except PlatformError as exc:
            require(exc.code == "CONTROL_MODE_MISMATCH", "EXAMPLE_FAILED", str(exc))
            print("EXPECTED_ERROR", exc.code)
        await client.stop()
        await client.release_control()
        print("MOCK_EXAMPLE=PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    asyncio.run(run(parser.parse_args().url))
