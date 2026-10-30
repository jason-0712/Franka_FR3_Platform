#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
python3 docker/verify_sources.py
python3 docker/prepare_wheels.py
task_revision="$(git rev-parse HEAD)"
if [ -n "$(git status --porcelain --ignore-submodules=all)" ]; then
  task_revision="${task_revision}-dirty"
fi
mkdir -p artifacts/franka_platform/docker
exec docker build --platform linux/amd64 \
  --build-arg "SOURCE_REVISION=$task_revision" \
  --build-arg IMAGE_VERSION=0.1.0-preview \
  --iidfile artifacts/franka_platform/docker/image-id.txt \
  -t "${1:-jiahanyu/franka_fr3:0.1.0-preview}" .
