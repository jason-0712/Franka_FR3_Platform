#!/usr/bin/env python3
"""Inspect fresh subscription data and own ROS endpoints; never start hardware."""
import argparse
import base64
import json
from pathlib import Path
import time

from franka_platform.backends.ros2 import ROS2Backend
from franka_platform.config import load
from franka_platform.core import Platform
from franka_platform.protocol import PlatformError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration-s", type=float, default=5)
    args = parser.parse_args()
    cfg = load(args.config)
    if cfg["backend"] != "real" or cfg["permission"] != "read_only":
        parser.error("Requires real + read_only")
    backend = ROS2Backend(cfg)
    platform = Platform(cfg, backend)
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        samples = []
        deadline = time.monotonic()+min(max(args.duration_s, 1), 30)
        while time.monotonic() < deadline:
            time.sleep(.2)
            obs = platform.observation()
            samples.append({"server_monotonic_s": obs["server_monotonic_s"], "freshness": obs["freshness"],
                            "cameras": [{k: v for k, v in c.items() if k != "data_base64"} for c in obs["cameras"]]})
        publishers = backend.node.get_publisher_names_and_types_by_node(backend.node.get_name(), backend.node.get_namespace())
        status = platform.status()
        for cam in obs["cameras"]:
            if cam["available"]:
                (directory/(cam["name"]+"."+cam["encoding"])).write_bytes(base64.b64decode(cam["data_base64"], validate=True))
        (directory/"observation.json").write_text(json.dumps(obs, ensure_ascii=False, indent=2))
        report = {"schema_version": 1, "stage": "C", "status": "PASS" if obs["freshness"]["action_blocker"] is None else "FAIL",
                  "platform_status": status, "samples": samples, "own_publishers": publishers,
                  "actuator_write_count": backend.writes, "notes": "No controller startup, goals, switching, homing or recovery"}
        (directory/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in report.items() if k != "samples"}, ensure_ascii=False, indent=2))
    finally:
        platform.close()


if __name__ == "__main__":
    main()
