#!/usr/bin/env python3
"""Expand the installed robot description for FK, without opening a robot connection."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    import yaml
    import xacro
    from ament_index_python.packages import get_package_share_directory
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())
    source = Path(get_package_share_directory("crisp_controllers_robot_demos"))/"config/fr3/fr3_single.urdf.xacro"
    xml = xacro.process_file(str(source), mappings={"robot_ip": cfg.get("robot", {}).get("ip") or "UNSET_FOR_FK_ONLY",
        "hand": "true", "load_gripper": "true", "arm_prefix": "", "use_fake_hardware": "false",
        "fake_sensor_commands": "false"}).toprettyxml()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml)
    print(json.dumps({"source": str(source), "output": str(out), "sha256": hashlib.sha256(xml.encode()).hexdigest(),
                      "hardware_connections": 0}))


if __name__ == "__main__":
    main()
