#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ "${1:---plan}" = --plan ]; then
  echo 'Default: attach the subscription-only platform to an existing audited state source.'
  echo 'A new controller_manager is never started implicitly. For a stopped installation use --read-only CONFIG after checking no manager is running.'
  exit 0
fi
if [ "${1:-}" != --read-only ] || [ "$#" -ne 2 ]; then
  echo 'Use --plan or --read-only FIELD_CONFIG. Real execute is blocked pending watchdog/stop acceptance.' >&2
  exit 2
fi
if [ "${ROS_DISTRO:-}" != humble ]; then echo 'Source the verified Humble workspace first.' >&2; exit 2; fi
exec ros2 launch "$task_root/scripts/franka_platform/observe.launch.py" config:="$2"
