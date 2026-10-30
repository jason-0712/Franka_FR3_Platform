#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
case "${1:---plan}" in
  --plan)
    cat <<'PLAN'
1. --python: create isolated .venvs/franka-platform, install pinned lightweight Python dependencies.
2. --patches: verify pinned nested commits, apply recorded patches idempotently.
3. --build-ros: require an already prepared Humble environment; build only the existing platform control stack.
No apt upgrades, kernel/network changes, restarts, ROS startup, or device commands are automatic.
PLAN
    ;;
  --python)
    task_env="${FRANKA_PLATFORM_VENV:-$task_root/.venvs/franka-platform}"
    env -u PYTHONPATH -u PYTHONHOME "${PYTHON:-python3}" -m venv "$task_env"
    env -u PYTHONPATH -u PYTHONHOME "$task_env/bin/python" -m pip install -c "$task_root/franka_platform/constraints.txt" websockets PyYAML setuptools wheel packaging
    env -u PYTHONPATH -u PYTHONHOME "$task_env/bin/python" -m pip install --no-build-isolation --no-deps -e "$task_root/franka_platform"
    env -u PYTHONPATH -u PYTHONHOME "$task_env/bin/python" -m pip check
    ;;
  --patches)
    exec bash "$task_root/scripts/apply_nested_repo_patches.sh"
    ;;
  --build-ros)
    if [ "${ROS_DISTRO:-}" != humble ]; then
      echo 'Require the verified ROS 2 Humble environment. Do not build under host Jazzy.' >&2
      exit 2
    fi
    cd "$task_root"
    exec colcon build --symlink-install --packages-up-to \
      libfranka franka_description franka_msgs franka_hardware \
      franka_semantic_components franka_example_controllers \
      franka_robot_state_broadcaster franka_gripper crisp_controllers \
      crisp_controllers_robot_demos
    ;;
  *) echo 'Use --plan, --python, --patches, or --build-ros' >&2; exit 2 ;;
esac
