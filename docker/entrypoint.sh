#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /opt/franka-control/setup.bash
set -u
task_python=/opt/franka-platform/venv/bin/python
case "${1:-serve}" in
  serve)
    if [ "$#" -gt 0 ]; then shift; fi
    exec "$task_python" -m franka_platform.server --config "$FRANKA_PLATFORM_CONFIG" "$@"
    ;;
  self-test)
    shift
    exec "$task_python" /opt/franka-platform/scripts/franka_platform/acceptance.py \
      --output /tmp/franka-platform-acceptance.json "$@"
    ;;
  *) exec "$@" ;;
esac
