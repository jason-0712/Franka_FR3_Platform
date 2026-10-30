#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$task_root"
task_python="${FRANKA_PLATFORM_PYTHON:-$task_root/.venvs/franka-platform/bin/python}"
case "${1:---mock}" in
  --mock)
    exec env -u PYTHONPATH -u PYTHONHOME "$task_python" "$task_root/scripts/franka_platform/acceptance.py" "${@:2}"
    ;;
  --read-only)
    exec "$task_python" "$task_root/franka_platform/examples/read_only_client.py" "${@:2}"
    ;;
  --execute|--migration)
    echo 'NOT_RUN: requires the reviewed stage D/E field checklist; real execute adapter remains disabled.' >&2
    exit 2
    ;;
  *) echo 'Use --mock or --read-only [--url ...] [--output ...]' >&2; exit 2 ;;
esac
