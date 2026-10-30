# 部署与迁移

## 1. 采集与版本基线

先按首页递归 clone 本仓库，在工作区根目录检查依赖，再采集当前电脑：

```bash
bash scripts/franka_platform/collect_environment.sh \
  --container franka --output artifacts/franka_platform/environment_current
bash scripts/franka_platform/doctor.sh
bash scripts/apply_nested_repo_patches.sh --check
```

采集操作不改系统，不启动设备，不恢复故障。现场配置和校准文件另行保存；不要提交凭据或把 `robot.local.yaml` 覆盖成公开模板。公开仓库只包含配置模板和摘要证据，完整环境报告保留在现场。

纯平台依赖固定为 websockets 15.0.1、PyYAML 6.0.3；构建工具固定为 setuptools 79.0.1、wheel 0.45.1、packaging 25.0。选择 setuptools<80 是为了兼容现场 colcon-core 的实际约束；显式固定 packaging 避免旧 ROS 系统包与构建工具混用时的版本冲突。

另一台电脑应使用本仓库固定主提交和子模块提交。`SOURCE_BASELINE.json` 记录原始来源；`collect_environment.sh` 记录当前 checkout、递归子模块（包括 `libfranka/common`）和实际文件指纹。不要以 README 当前分支取代源码锁，也不要复制 `build/install/log`。可额外生成当前有效源码快照及 SHA256：

```bash
bash scripts/franka_platform/bootstrap.sh --patches
bash scripts/franka_platform/export_source.sh \
  --output artifacts/franka_platform/source-snapshot.tar.gz
(cd artifacts/franka_platform && sha256sum -c source-snapshot.tar.gz.sha256)
```

校验命令需在清单所在目录运行，或自行提供归档的路径。快照根目录为 `Franka_FR3_Platform/`，包含平台、控制依赖与文件哈希，不携带 Git 元数据、构建目录、数据集、现场配置或模型权重。本仓库没有包含 StarVLA/FLASH。先运行补丁入口，使平台必需的一个控制描述补丁生效，再导出；无 Git 元数据的快照不要再调用补丁脚本。全部递归子模块须已 checkout。需要重新验证“从原始提交应用补丁”的检查，应使用完整 Git checkout。

## 2. 纯 Python 平台

Linux/macOS 上使用 Python 3.10+，不先安装 ROS、PyTorch 或 StarVLA：

```bash
bash scripts/franka_platform/bootstrap.sh --python
bash scripts/franka_platform/run_acceptance.sh --mock
bash scripts/franka_platform/start_platform.sh
```

脚本路径从自身位置解析，不包含开发者用户名。可以通过 `FRANKA_PLATFORM_VENV` 指定安装 venv，通过 `FRANKA_PLATFORM_PYTHON` 指定运行解释器。重新安装不会覆盖现场 YAML。脚本默认只显示系统准备计划；不自动执行 apt 升级、网络配置、内核安装或重启。

完全离线安装可在联网电脑按目标 Python/架构准备所需 wheels，再运行：

```bash
python3 -m venv .venvs/franka-platform
.venvs/franka-platform/bin/python -m pip install --no-index --find-links WHEEL_DIR \
  websockets==15.0.1 PyYAML==6.0.3 setuptools==79.0.1 wheel==0.45.1 packaging==25.0
.venvs/franka-platform/bin/python -m pip install --no-index --no-deps WHEEL_DIR/franka_platform-0.1.0-py3-none-any.whl
```

`WHEEL_DIR` 为实际准备目录，不是仓库内置的权重或 GPU 环境。依赖 wheels 须按目标 Python/架构准备；本仓库不提交这些二进制安装包。

## 3. Linux 控制主机

先依据实际机器人系统版本核对 [libfranka 兼容表](https://frankarobotics.github.io/docs/doc/libfranka/docs/compatibility_matrix.html) 与 [Humble 兼容表](https://frankarobotics.github.io/docs/doc/franka_ros2_humble/franka_ros2/doc/compatibility_matrix.html)。本轮保留当前源码组合，未要求升级。实时内核与权限按 [官方实时配置](https://frankarobotics.github.io/docs/doc/libfranka/docs/real_time_kernel.html) 逐项准备、记录重启及重新登录要求；Docker 镜像不替代主机内核、权限或网卡设置。

已有部署是 Ubuntu 24.04 主机加 Ubuntu 22.04/Humble 容器。若新主机选择原生方式，应先准备与固定源码一致的 Humble/Ubuntu 22.04 依赖。不要在宿主机 Jazzy 环境直接构建原 Humble 工作区。已采集的 apt 清单是版本证据，尚不是无条件跨 Ubuntu 发行版可安装的锁文件。

在已准备的 Humble 控制环境中重建：

```bash
source /opt/ros/humble/setup.bash
# 完整 Git checkout 才运行此步：
bash scripts/franka_platform/bootstrap.sh --patches
bash scripts/franka_platform/bootstrap.sh --build-ros
source install/setup.bash
```

新路径必须重新构建，确认产物链接的 libfranka 及硬件插件来自该源码。主机系统准备、ROS 包安装和构建仍是分开的步骤。本轮已在[独立 Docker 镜像](docker.md)中从固定源码重建原生控制依赖并加载动态库；第二台电脑构建及新控制栈连接硬件尚未执行。

本仓库仅保留 `crisp_controllers`、`crisp_controllers_demos`、`franka_broadcasters`、`libfranka` 四个顶层控制 submodule，以及原样 vendored 的 Franka ROS/描述；不需要原 `crisp_py`、`crisp_gym` 或 Quest/VLA 环境。上游 demos 的完整 launch 仍可能引用旧 adapter，平台只使用本仓库的只读入口。构建入口显式选择原生控制依赖。已通过的干净构建属于 Humble 容器环境，尚未在另一台物理主机上验收。

## 4. 配置

```bash
cp franka_platform/configs/robot.example.yaml franka_platform/configs/robot.local.yaml
```

填写现场机器人 IP、网卡、Domain、middleware、topic、关节顺序、base/tool、两路相机序列号及 optical frame。只读允许执行限制留空；dry-run 要求所有用于校验的限制与 `controller_to_tool` 有明确值及来源。真实 execute 始终拒绝，直至另行完成执行适配与验收。

使用实际控制环境的 Python 展开已安装描述，只生成 XML，不连接机器人：

```bash
python3 scripts/franka_platform/export_robot_description.py \
  --config franka_platform/configs/robot.local.yaml \
  --output artifacts/franka_platform/robot.urdf
```

将生成文件的绝对路径填入 `ros.robot_description_file`，保存 SHA256。该文件必须与实际工具安装匹配。网络服务的 Python 必须与 ROS Python ABI 一致；本机是 Python 3.10，不能把 Python 3.13 venv 注入 Humble。

## 5. 只读入口

优先订阅已有状态源。在 Humble 环境中按配置设置 Domain 与 middleware，再启动已安装平台 wheel 的解释器：

```bash
export ROS_DOMAIN_ID=30              # 以现场 YAML 为准
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export FRANKA_PLATFORM_CONFIG="$PWD/franka_platform/configs/robot.local.yaml"
export FRANKA_PLATFORM_PYTHON=/实际ROS兼容venv/bin/python
bash scripts/franka_platform/start_platform.sh
```

若确实没有状态源，`start_robot.sh --plan` 先显示边界。已确认不存在另一个 controller_manager，且现场 IP 已填写后，才显式使用：

```bash
bash scripts/franka_platform/start_robot.sh --read-only /绝对路径/robot.local.yaml
```

该入口只启动关节状态 broadcaster 和标准夹爪状态驱动，不启动轨迹/阻抗控制器、CRISP 手爪 adapter 或恢复动作；启动前会做 ROS graph 重复管理器检查。它仍会建立硬件连接并使用原硬件描述，未在本次交付中实际启动过。已经有数据时不需要运行它。

只读采集与诊断：

```bash
bash scripts/franka_platform/run_acceptance.sh --read-only \
  --output artifacts/franka_platform/real_observation
# 必须使用安装了平台依赖的 Python 执行网络诊断
PYTHON=.venvs/franka-platform/bin/python bash scripts/franka_platform/doctor.sh \
  --platform-url ws://127.0.0.1:8765
```

采集成功不代表当前控制器、停止和执行状态均已验证。缺少关节数据时图像仍能用于定位，但不会偷偷把观察配置从 dual_camera 降级。

## 6. 相机启动

已存在相机驱动时继续订阅；不重复启动。填写 `camera_image` 的 digest 和两路序列号后：

```bash
bash scripts/franka_platform/start_cameras.sh --config /绝对路径/robot.local.yaml
# 审阅输出的命令后，显式执行；不会启动机械臂
bash scripts/franka_platform/start_cameras.sh --config /绝对路径/robot.local.yaml --execute
```

命令保留现有部署的 host network、USB `/dev` 和 privileged 设备访问方式；不是仅靠普通无设备容器运行。检测到已知相机容器会拒绝重复占用。新入口只为模型无关 RGB 观测开启彩色图；原有主相机的深度配置继续保留在原 Compose 中。本轮仅核对生成计划，没有重启相机。

## 7. 远端 SDK

服务固定监听 loopback，远端使用现有可信 SSH 通道：

```bash
ssh -N -L 8765:127.0.0.1:8765 用户@控制电脑
```

在远端安装相同平台 wheel 后，运行同一个 `read_only_client.py`；图像从 WebSocket 传输，无需挂载控制电脑目录。SSH 用户/地址由现场填写。本轮验证了独立进程与同主机容器的连接；没有把这称为另一台物理电脑迁移通过。

## 8. 停止、恢复和迁移验收

Ctrl-C 关闭平台服务；Mock 活动目标被中止。真实只读服务关闭只会销毁订阅，不发送停止或夹爪目标。已有控制器的硬件停止流程必须按现场已验证方法执行，平台 stop 不是硬件急停。

故障后先排查原因，显式释放旧会话并重新连接；不自动恢复、回零、homing 或重放缓存。控制器超时不能用循环重启 launch 掩盖。

第二台电脑按顺序保存：主机与机器人版本记录、全新路径构建日志、Mock 报告、真实状态与两路图像、控制器/硬件接口状态、最后由现场人员完成三类动作/夹爪/停止/断线监督试验。保持同一机器人与相机安装；安装变化时重新处理标定。参见 [验收报告中的现场表](acceptance-report.md)。
