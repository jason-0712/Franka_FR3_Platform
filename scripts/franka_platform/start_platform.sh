#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$task_root"
exec "${FRANKA_PLATFORM_PYTHON:-$task_root/.venvs/franka-platform/bin/python}" -m franka_platform.server \
  --config "${FRANKA_PLATFORM_CONFIG:-$task_root/franka_platform/configs/mock.yaml}" "$@"
