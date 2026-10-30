#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "${FRANKA_PLATFORM_PYTHON:-$task_root/.venvs/franka-platform/bin/python}" "$task_root/scripts/franka_platform/ops.py" cameras "$@"
