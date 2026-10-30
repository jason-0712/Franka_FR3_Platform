# 实施与验收报告

日期：2026-10-30。版本：`franka_platform` 0.1.0 预览交付。源码从原 `franka_ws` 基线独立整理，必要控制依赖和文件哈希见根目录 [SOURCE_BASELINE.json](../../SOURCE_BASELINE.json)。

**离线平台已完成；原控制电脑真实只读观测已通过。真机执行适配尚未开放，第二台电脑迁移未验收。** 本仓库没有包含 StarVLA、FLASH、原现场配置、相机照片或完整环境清单。

## 分阶段结果

| 阶段/检查 | 结果 | 范围与证据 |
| --- | --- | --- |
| A 源码与环境审计 | PASS（缺项已列） | [源码审计](source-audit.md)、[来源锁](../../SOURCE_BASELINE.json)。原完整环境证据保留在现场；新机用采集脚本重新生成 |
| B 原工作区离线验收 | PASS | 无模型依赖 Python 3.13.13，21 项全部通过；[机器报告](evidence/original-mock-acceptance.json) |
| B Python 3.10 兼容性 | PASS | 原 Humble 容器隔离 venv，20 项核心测试通过；[日志](evidence/original-python310-tests.log) |
| B 新仓库复测 | PASS | 独立路径、全新轻量 venv、21 项全部通过；[机器报告](evidence/platform-mock-acceptance.json)、[日志](evidence/platform-mock-tests.log)。包含本仓库一个补丁的干净恢复、重复应用及错版本拒绝 |
| B SDK/独立进程 | PASS | 宿主服务、宿主只读 SDK、容器动作 SDK，通过真实 WebSocket；[原始联调摘要](evidence/original-transport-summary.json)。同一物理电脑，不作为第二机迁移 |
| C 原控制电脑只读 | PASS（拆分前） | 七关节、夹爪、FK、双相机和真实 WebSocket；自身节点仅 `/parameter_events` 发布者，写入 0；[公开摘要](evidence/original-readonly-summary.json) |
| 控制器状态查询 | FAIL | `/controller_manager/list_controllers` 超时；状态可读不能证明控制器或 FCI 执行状态就绪 |
| Docker 干净原生构建 | PASS | 官方 Humble 基镜像、固定控制源码重新编译；20 个原生动态库可在最终镜像中加载；[Docker 部署](docker.md) |
| Docker 核心与服务 | PASS | 镜像内 20 项核心测试；Mock 只读、三类动作、独立夹爪与 dry-run 通过；补丁恢复测试因无 Git 元数据跳过 |
| C Docker 真实只读 | PASS | 新平台镜像订阅现有状态及双相机，通过真实 WebSocket，执行器写入 0；没有重新启动硬件或相机 |
| 新控制栈硬件启动 | NOT_RUN | 新原生库已编译和加载，尚未连接机器人运行；只读数据由原有运行控制栈提供 |
| D 当前电脑执行 | NOT_RUN | 既有控制器缺独立目标超时和已验证停止/切换流程；自动恢复行为及现场限制待补齐 |
| E 第二台电脑迁移 | NOT_RUN | 尚未访问另一台物理控制电脑；换目录及同机容器不等于换机 |

## 三类动作与夹爪

“ROS 映射通过”表示纯转换得到已审计的消息结构，没有向真实控制话题或 action server 发送目标。

| 动作 | Mock | ROS 只读映射 | 当前电脑真机执行 | 第二台电脑 |
| --- | --- | --- | --- | --- |
| `cartesian_absolute` | PASS | PASS：`PoseStamped`，含 TCP/控制点换算 | NOT_RUN | NOT_RUN |
| `cartesian_delta` | PASS | PASS：指定观测的基座增量转换成绝对目标 | NOT_RUN | NOT_RUN |
| `joint_absolute` | PASS | PASS：七关节 `JointState`，严格顺序，零目标速度，无 IK | NOT_RUN | NOT_RUN |
| 独立夹爪总宽度 | PASS | PASS：`Move` 的总宽度与速度 | NOT_RUN | NOT_RUN |

证据：[语义、错误与映射测试](../../franka_platform/tests/test_platform.py)、[新仓库验收结果](evidence/platform-mock-acceptance.json)。Mock 反馈完成与超时通过，不模拟真实动力学。真实 capabilities 对四项均报告 `protocol_implemented=true`、`backend_executable=false`、`hardware_verified=false`，并报告 `completion_feedback=false`。`real + execute` 返回 `EXECUTION_NOT_VERIFIED`，不能只修改配置解锁。

## 测试范围与复现

```bash
bash scripts/franka_platform/bootstrap.sh --python
bash scripts/franka_platform/run_acceptance.sh --mock
bash scripts/apply_nested_repo_patches.sh --check
```

覆盖三类动作与独立夹爪；维度/顺序/有限值/四元数/frame/限制；非交换旋转、非零 TCP、指定参考及最新实测状态；缓存传感器继续老化；幂等、重复参考、所有权、epoch、切换失败；断线、故障、租约及命令超时；反馈完成；只读与 dry-run 零写入；双相机缺失/过期/时间差；实际 WebSocket 往返。watchdog 在没有后续网络请求时仍处理超时。

补丁测试只操作临时干净 checkout，验证 `--check` 零变更、首次应用、再次跳过及错误提交拒绝。没有 Git 元数据的源码快照会跳过该项；普通 clone 未取回控制 submodule 时也明确跳过，核心测试仍可运行。完整递归 checkout 应为 21 项通过、0 跳过。

原控制电脑 5 秒只读采集取得 25 组样本，最大状态年龄 **1.686 ms**，最大配对偏差 **61.337 ms**，最大图像年龄 **62.330 ms**。主图 1280×720、腕图 640×480，均为真实 `ros_compressed_image` JPEG。配对取最新收到样本，未声明硬件同步。实际 URDF 的平台 FK 与 PyKDL 在三组位置上的最大位置/旋转矩阵差为 `6.661338147750939e-16`；数学扰动没有发送给设备。这不能替代工具安装和标定确认。

上述硬件结果属于拆分前的原运行环境，平台运行核心文件原样带入此仓库。公开摘要移除了原始图像、关节样本、现场 IP/序列号、标定及完整环境清单；完整原始证据在原电脑保留。拆分没有新增一次真机执行验证。

新增 Docker 检查在独立平台镜像中完成：20 个原生动态库加载通过；真实只读节点仅有 `/parameter_events` 发布者，控制权请求返回 `READ_ONLY`。镜像内 Pinocchio 4.0.0 对同一现场 URDF 的三组离线 FK 与平台算法比较，最大位置差 `1.6653345369377348e-16` m，最大旋转矩阵差 `7.771561172376096e-16`。原始关节与图像未公开；扰动仅用于数学计算。这些检查没有启动新编译的硬件插件，也没有推进 D/E 执行验收。镜像已按 digest 拉取并通过隔离自测；[脱敏验证摘要](evidence/docker-preview-summary.json)与[发布清单](../../docker/image-release.json)记录实际版本和范围。

## D/E 的具体待办

| 缺项 | 下一步与证据 |
| --- | --- |
| 机器人 System Version / 软件兼容 | 到 Desk/系统页面记录实际版本，对照部署文档的官方表，保存与 libfranka/ROS 的配对结果 |
| 实时权限 | 原 shell `rtprio=0`；按官方流程准备并记录实际控制进程的 rtprio、memlock、调度与网络表现 |
| 控制器状态 | 在正确 Humble/Domain/middleware 中排查下面的只读查询；超时不能视为就绪 |
| 工具和执行限制 | 核实 base/tool/固定变换、实物安装、标定及 SHA；填写现场关节/工作空间/步长/夹爪限制，不能照抄 Mock |
| 执行后端工程 | 补齐不依赖 Python/网络进程的目标 watchdog、可验证 stop/hold、资源切换、完成反馈；处理既有 automaticErrorRecovery 行为后再开放写入 |
| 现场监督 | 排除外部遥操/目标发布源，安排熟悉硬件停止的人员；由恒定实测目标开始，再逐项进行小幅动作与超时/断线/停止试验 |
| 新电脑迁移 | 按部署文档准备新 Linux/实时环境，固定 checkout，新路径重建，不复制 build/install/log；先 Mock，再双相机只读，D 完成后才进行 E 的执行复测 |

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=30  # 以现场配置为准
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ros2 control list_controllers -c /controller_manager
ros2 control list_hardware_interfaces -c /controller_manager
ros2 topic info /target_pose -v
ros2 topic info /target_joint -v
```

本版本没有合法的真机执行启动命令，`run_acceptance.sh --execute` 明确返回未运行。现场每项保存请求、参考观测、实测反馈、误差/容差、模式/epoch、终态与异常。没有完成反馈就不能写 completed。只有在另一台物理电脑完成约定检查后，E 才能改为 PASS。
