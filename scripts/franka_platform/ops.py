#!/usr/bin/env python3
"""Read-only inventory, deployment plans and diagnostic reports (stdlib only)."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def command(argv, timeout=20, cwd=ROOT):
    try:
        p = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=timeout)
        return {"status": "PASS" if p.returncode == 0 else "FAIL", "command": argv,
                "exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except FileNotFoundError:
        return {"status": "SKIP", "command": argv, "reason": "executable unavailable"}
    except subprocess.TimeoutExpired:
        return {"status": "FAIL", "command": argv, "reason": "timeout"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def delivery_file(path):
    excluded = {"build", "install", "log", "dist", "__pycache__", ".pytest_cache"}
    return path.is_file() and not any(p in excluded or p.endswith(".egg-info") for p in path.parts) \
        and not path.name.endswith((".pyc", ".local.yaml"))


def source_report():
    revision = command(["git", "rev-parse", "HEAD"])
    report = {"root_commit": revision.get("stdout", "").strip() if revision["status"] == "PASS" else None,
              "root_status": command(["git", "status", "--porcelain=v1"]), "nested_repositories": {},
              "patches": {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT/"patches/nested_repos").glob("*.patch"))}}
    def visit(repository, prefix=Path()):
        tree = command(["git", "ls-tree", "-r", "HEAD"], cwd=repository)
        for line in tree.get("stdout", "").splitlines():
            meta, relative = line.split("\t", 1)
            if not meta.startswith("160000 "):
                continue
            path = prefix/relative
            checkout = ROOT/path
            entry = {"pinned_commit": meta.split()[2], "checkout_present": (checkout/".git").exists()}
            if entry["checkout_present"]:
                entry["actual_commit"] = command(["git", "rev-parse", "HEAD"], cwd=checkout).get("stdout", "").strip()
                entry["status"] = command(["git", "status", "--porcelain=v1"], cwd=checkout)
                entry["tracked_diff"] = command(["git", "diff", "HEAD", "--binary"], cwd=checkout)
            report["nested_repositories"][str(path)] = entry
            if entry["checkout_present"]:
                visit(checkout, path)
    visit(ROOT)
    # The root commit covers the vendored franka_ros2 / franka_description trees.
    report["platform_files"] = {str(p.relative_to(ROOT)): sha(p)
        for directory in (ROOT/"franka_platform", ROOT/"scripts/franka_platform", ROOT/"docs/franka_platform")
        for p in sorted(directory.rglob("*")) if delivery_file(p)}
    report["delivery_root_changes"] = {p: sha(ROOT/p) for p in
        (".gitignore", ".gitmodules", "README.md", "SOURCE_BASELINE.json", "scripts/apply_nested_repo_patches.sh")}
    for path, entry in report["nested_repositories"].items():
        if not entry["checkout_present"]:
            continue
        checkout = ROOT/path
        untracked = command(["git", "ls-files", "--others", "--exclude-standard"], cwd=checkout)["stdout"].splitlines()
        entry["untracked_sha256"] = {p: sha(checkout/p) for p in untracked if (checkout/p).is_file()}
    return report


def collect(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "collected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "workspace": str(ROOT), "source": source_report(), "checks": {},
              "ros_environment": {k: os.environ.get(k) for k in ("ROS_DISTRO", "ROS_DOMAIN_ID", "RMW_IMPLEMENTATION")}}
    cmds = {"kernel": ["uname", "-a"], "os": ["cat", "/etc/os-release"],
            "cpu": ["lscpu"], "interfaces": ["ip", "-j", "address"], "routes": ["ip", "-j", "route"],
            "python": [sys.executable, "--version"], "pip": [sys.executable, "-m", "pip", "freeze", "--all"],
            "apt": ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Architecture}\n"],
            "apt_sources": ["bash", "-c", "cat /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null"],
            "rt_limits": ["bash", "-c", "ulimit -r; ulimit -l; id; cat /sys/kernel/realtime 2>/dev/null"],
            "containers": ["docker", "ps", "-a", "--format", "{{.Names}} {{.Image}} {{.Status}}"],
            "images": ["docker", "image", "inspect", "franka:latest", "realsense_ros2:latest", "--format", "{{.Id}} {{json .RepoDigests}}"]}
    for name, cmd in cmds.items():
        report["checks"][name] = command(cmd)
    if args.container:
        # Fixed read-only commands; no credentials or complete environment dump.
        report["checks"]["control_container"] = command(["docker", "exec", args.container, "bash", "-lc",
            "cat /etc/os-release; python3 --version; ls /opt/ros; dpkg-query -W -f='${Package}\\t${Version}\\n'"], timeout=30)
        report["checks"]["control_mounts"] = command(["docker", "inspect", args.container, "--format", "{{json .Mounts}}"])
        report["checks"]["control_python"] = command(["docker", "exec", args.container, "python3", "-m", "pip", "freeze", "--all"])
    (output/"environment.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (output/"source-lock.json").write_text(json.dumps(report["source"], ensure_ascii=False, indent=2))
    print(json.dumps({"environment_report": str(output/"environment.json"), "actuator_writes": 0}))


def doctor(args):
    checks = {}
    checks["python"] = {"status": "PASS" if sys.version_info >= (3, 10) else "FAIL", "version": sys.version}
    checks["source"] = {"status": "PASS" if (ROOT/".git").exists() else "FAIL"}
    checks["patches"] = command(["bash", str(ROOT/"scripts/apply_nested_repo_patches.sh"), "--check"])
    for name in ("robot_network", "FCI", "ROS", "dual_camera", "controller_execution", "second_computer"):
        checks[name] = {"status": "NOT_RUN", "reason": "offline diagnosis; explicitly select a hardware stage"}
    if args.ros:
        for name, cmd in {"ROS": ["ros2", "topic", "list", "-t"],
                          "controllers": ["ros2", "control", "list_controllers"]}.items():
            checks[name] = command(cmd, timeout=15)
    if args.platform_url:
        import asyncio
        from franka_platform.client import Client
        async def sample():
            async with Client(args.platform_url) as client:
                return await client.get_status(), await client.get_observation()
        try:
            status, obs = asyncio.run(sample())
            checks["platform"] = {"status": "PASS", "detail": status}
            checks["robot_state"] = {"status": "PASS" if obs["freshness"]["action_blocker"] is None else "FAIL",
                                      "detail": obs["freshness"]}
            for c in obs["cameras"]:
                checks["camera_"+c["name"]] = {"status": "PASS" if c["available"] and
                    c["age_s"] is not None and c["age_s"] <= obs["freshness"]["camera_max_age_s"] else "FAIL",
                    "detail": {k: v for k, v in c.items() if k != "data_base64"}}
        except Exception as exc:
            checks["platform"] = {"status": "FAIL", "reason": str(exc)}
    report = {"schema_version": 1, "checks": checks, "actuator_writes": 0}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(any(c["status"] == "FAIL" for c in checks.values()))


def camera_plan(args):
    import yaml
    cfg = yaml.safe_load(Path(args.config).read_text())
    image = cfg.get("camera_image")
    if not image or "@sha256:" not in image or len(cfg.get("cameras", [])) != 2:
        raise SystemExit("Need camera_image repository@sha256:digest and exactly two cameras")
    commands = []
    for camera in cfg["cameras"]:
        if not camera.get("serial") or not camera.get("color_profile"):
            raise SystemExit("Need each camera serial and color_profile")
        topic = camera["topic"].removesuffix("/compressed").removesuffix("/color/image_raw")
        namespace, name = topic.rsplit("/", 1)
        commands.append(["docker", "run", "-d", "--rm", "--name", "franka_platform_"+camera["name"],
            "--network", "host", "--privileged", "--volume", "/dev:/dev",
            "-e", "ROS_DOMAIN_ID="+str(cfg["ros"]["domain_id"]), "-e", "RMW_IMPLEMENTATION="+cfg["ros"]["middleware"],
            image, "bash", "-lc", "source /opt/ros/humble/setup.bash && exec ros2 launch realsense2_camera rs_launch.py "+
            " ".join(shlex.quote(v) for v in ["camera_namespace:="+namespace.lstrip('/'),
            "camera_name:="+name, "serial_no:=_"+str(camera["serial"]),
            "rgb_camera.color_profile:="+camera["color_profile"], "enable_depth:=false"])])
    print(json.dumps({"status": "PLAN", "commands": commands, "note": "Stop existing camera owners first; review USB permissions"}, indent=2))
    if args.execute:
        running = command(["docker", "ps", "--format", "{{.Names}}"])
        if running["status"] != "PASS":
            raise SystemExit("Cannot inspect existing camera containers")
        if any(n in running["stdout"].splitlines() for n in
               ("franka_dual_realsense", "franka_platform_primary", "franka_platform_wrist")):
            raise SystemExit("Existing camera owner detected; stop it explicitly before starting another")
        subprocess.run(["docker", "image", "inspect", image], check=True, stdout=subprocess.DEVNULL)
        started = []
        try:
            for cmd in commands:
                subprocess.run(cmd, check=True)
                started.append(cmd[cmd.index("--name")+1])
        except subprocess.CalledProcessError:
            for name in started:
                subprocess.run(["docker", "stop", name], check=False)
            raise


def export_snapshot(args):
    """Portable source plus exact nested patches, without Git internals or build products."""
    import tarfile
    import io
    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    paths = set(command(["git", "ls-files"])["stdout"].splitlines())
    provenance = source_report()
    submodules = provenance["nested_repositories"]
    for path, entry in submodules.items():
        if not entry["checkout_present"]:
            raise SystemExit("Missing dependency "+path+"; run git submodule update --init --recursive before export")
        checkout = ROOT/path
        for p in command(["git", "ls-files"], cwd=checkout)["stdout"].splitlines():
            paths.add(str(Path(path)/p))
    for directory in ("franka_platform", "scripts/franka_platform", "docs/franka_platform"):
        paths.update(str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob("*") if p.is_file())
    manifest = {}
    with tarfile.open(out, "w:gz") as archive:
        for relative in sorted(paths):
            path = ROOT/relative
            if delivery_file(path):
                archive.add(path, arcname="Franka_FR3_Platform/"+relative, recursive=False)
                manifest[relative] = sha(path)
        data = json.dumps({"schema_version": 1, "provenance": provenance, "files_sha256": manifest},
                          ensure_ascii=False, indent=2).encode()
        header = tarfile.TarInfo("Franka_FR3_Platform/SOURCE_SNAPSHOT.json")
        header.size = len(data)
        archive.addfile(header, io.BytesIO(data))
    lock = out.with_suffix(out.suffix+".sha256")
    lock.write_text(sha(out)+"  "+out.name+"\n")
    print(json.dumps({"source_snapshot": str(out), "sha256": sha(out)}))


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="mode", required=True)
    p = subs.add_parser("collect")
    p.add_argument("--output", default="artifacts/franka_platform/environment")
    p.add_argument("--container")
    p = subs.add_parser("doctor")
    p.add_argument("--output", default="artifacts/franka_platform/doctor.json")
    p.add_argument("--ros", action="store_true")
    p.add_argument("--platform-url")
    p = subs.add_parser("cameras")
    p.add_argument("--config", required=True)
    p.add_argument("--execute", action="store_true")
    p = subs.add_parser("export")
    p.add_argument("--output", default="artifacts/franka_platform/source-snapshot.tar.gz")
    args = parser.parse_args()
    if args.mode == "collect":
        collect(args)
    elif args.mode == "doctor":
        return doctor(args)
    elif args.mode == "cameras":
        camera_plan(args)
    else:
        export_snapshot(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
