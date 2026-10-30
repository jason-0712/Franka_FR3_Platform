#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash

# The upstream CPack helper requires Git tags even for an ordinary C++ build.
# Build from the pinned exported sources without copying Git credentials/history.
# This changes packaging metadata only; the library version remains 0.19.0.
python3 - <<'PY'
from pathlib import Path
p = Path('src/libfranka/CMakeLists.txt')
old = 'set_version_from_git(PACKAGE_VERSION PACKAGE_TAG)'
assert p.read_text().count(old) == 1
p.write_text(p.read_text().replace(old,
    'set(PACKAGE_VERSION "${libfranka_VERSION}")\nset(PACKAGE_TAG "${libfranka_VERSION}")'))
for name in ('cartesian_controller.cpp', 'pose_broadcaster.cpp'):
    p = Path('src/crisp_controllers/src')/name
    old = '#include <pinocchio/algorithm/frames.hxx>'
    assert p.read_text().count(old) == 1
    p.write_text(p.read_text().replace(old, '#include <pinocchio/algorithm/frames.hpp>'))
p = Path('src/crisp_controllers/CMakeLists.txt')
assert p.read_text().count('ament_package()') == 1
p.write_text(p.read_text().replace('ament_package()',
    'target_link_libraries(${PROJECT_NAME} PRIVATE pinocchio::pinocchio)\n\nament_package()'))
PY

colcon build --merge-install --install-base /opt/franka-control \
  --executor sequential --event-handlers console_direct+ \
  --packages-up-to libfranka franka_description franka_msgs franka_hardware \
    franka_semantic_components franka_example_controllers \
    franka_robot_state_broadcaster franka_gripper crisp_controllers crisp_controllers_robot_demos \
  --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DBUILD_TESTS=OFF \
    -DBUILD_EXAMPLES=OFF -DUSE_PRECOMPILED_HEADERS=ON

# This upstream package omits some CMake prerequisites from package.xml.
# Build it after those prerequisites have been installed above.
source /opt/franka-control/setup.bash
colcon build --merge-install --install-base /opt/franka-control \
  --executor sequential --event-handlers console_direct+ \
  --packages-select franka_broadcasters \
  --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF

python3 - <<'PY'
import hashlib, json
from pathlib import Path
names = sorted(p.name for p in Path('/opt/franka-control/share/ament_index/resource_index/packages').iterdir())
libraries = {str(p.relative_to('/opt/franka-control')): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in Path('/opt/franka-control').rglob('*.so*') if p.is_file() and not p.is_symlink()}
report = {'schema_version': 1, 'native_build': 'PASS', 'packages': names,
    'libraries_sha256': libraries, 'hardware_connections': 0,
    'build_adjustments': ['libfranka CPack metadata uses the fixed source version instead of git describe',
        'CRISP uses the public Pinocchio frames.hpp header in place of the internal frames.hxx include',
        'CRISP links the exported pinocchio::pinocchio target, including parser dependencies'],
    'hardware_execution': 'NOT_RUN', 'second_computer_migration': 'NOT_RUN'}
Path('/opt/franka-image-manifest/native-build.json').write_text(json.dumps(report, indent=2)+'\n')
PY
