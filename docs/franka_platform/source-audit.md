# 源码、环境与现场缺项审计

核查日期：2026-10-30。原控制工作区为 `franka_ws`，Git 基线 `e4ae615688d3f7b69748fb866b220c354fdf0ea8`。本仓库独立提取平台与所需控制依赖，没有改变原工作区的 FLASH、遥操或其他实验文件。下述硬件事实来自拆分前对原运行环境的只读检查；它不等于已在这个新 checkout 启动并重建硬件栈。

## 已确认的部署事实

宿主机为 Ubuntu 24.04.3，内核 `7.0.0-38-realtime`，`/sys/kernel/realtime=1`；当前 shell 的 `ulimit -r=0`，所以不能据此宣称已具备实时运行权限。宿主机装有 ROS Jazzy；已有 `franka` 容器是 Ubuntu 22.04.5 / ROS Humble / Python 3.10.12，工作区 `/home/ros/ros2_ws`，其 `src` 绑定至本工作区。新平台的纯 Python 验收另在没有 ROS、PyTorch、StarVLA 的 Python 3.13.13 venv 中运行。

已有相机容器 `franka_dual_realsense` 使用主机网络。原 Compose 写死了序列号、Domain 30 和 `realsense_ros2:latest`。本轮没有修改或重启这个容器；新入口从现场配置生成命令并要求 digest。

已记录的镜像引用：

| 用途 | 当前镜像的内容引用 |
| --- | --- |
| 原控制环境 | `jiahanyu/franka-ws@sha256:253e7ef589b2ccc26fa6e4e65bd9bdd58fc02b80dd3cc589745ebb061840a05d` |
| 原相机环境 | `jiahanyu/franka-ws@sha256:c413a421fdd4697e4ba2f082096bc5e931d5bc85639b664a05ede67f73c77f08` |

这些是实际本地 image inspect 得到的 RepoDigests，不是本轮发布的镜像。远端 manifest 查询已通过，不能把它等同另一台电脑已拉取或运行成功；没有向新仓库附带整个现场环境或容器快照。

## 固定源码

| 路径 | 固定提交 |
| --- | --- |
| `src/crisp_controllers` | `563842f181ac97cf53d64c96c1788e38ef01611c` |
| `src/crisp_controllers_demos` | `d12b9adb9161a6078b36da3bd93fa8e8422572e4` |
| `src/franka_broadcasters` | `f148ae178c94e7b7037fdb7e7044e1c70a92aa80` |
| `src/libfranka` | `4df37dd2b527f41ef34b76d6d4d3805864b09993`（源码标记 0.19.0） |
| `src/libfranka/common` | `d96c221a32c343384cbe2f77c61116ed58b84231`（递归子模块） |

`franka_ros2`、`franka_description` 是从原基线原样复制的跟踪文件，由 `SOURCE_BASELINE.json` 的逐文件哈希覆盖；`franka_hardware/package.xml` 为 2.0.2。本仓库使用标准 Git submodule 布局；环境工具递归记录每个实际 HEAD、diff 和未跟踪文件 SHA256，包括 `libfranka/common`。

原工作区四个记录补丁均已在干净副本验证。本仓库仅带入平台必需的控制描述补丁：`fr3.ros2_control.urdf.xacro` 加入已有硬件实现要求的 `version=0.0.0`。它是接口兼容占位字段，不能代替实际机器人系统版本。本仓库也复测首次应用、再次跳过、`--check` 零写入和错误版本拒绝。原 adapter、Dockerfile、其他实验 launch 补丁不带入本仓库，平台不依赖它们。

## 代码审计表

| 源码位置 | 观察到的行为 | 拟复用方式 | 验证状态 |
| --- | --- | --- | --- |
| `src/crisp_controllers/src/cartesian_controller.cpp:372` | `target_pose` 为 `geometry_msgs/PoseStamped`，`target_joint` 为 `sensor_msgs/JointState`，队列深度 1 | 保留已有消息映射 | 源码与纯映射测试通过；未发布真机目标 |
| 同文件 `parse_target_pose_`（495） | 直接读取米制位置与四元数，忽略 header.frame_id | 在平台先做 frame 校验与 TCP/控制点换算 | 非零偏移/旋转离线测试通过 |
| 同文件 `parse_target_joint_`（504） | 按数组顺序直接写 q_ref/dq_ref，不按 name 重排；底层没有充分尺寸保护 | 严格检查七维及完整顺序，拟发送七个零速度 | 按名称重排测量状态、拒绝错误命令顺序的测试通过 |
| `config/fr3/controllers.yaml`（4、112、158） | 1000 Hz；笛卡尔和关节阻抗均使用 `CartesianController` | 保留插件，不用 IK 替代关节接口 | 配置审计通过；实际实时调度未验收 |
| 同配置关节阻抗（126—155） | task stiffness 全 0，nullspace projector=none，关节 PD 和扭矩限制 | 关节模式映射到此控制器，而非把关节动作交给笛卡尔任务 | 源码支持；实机未验证 |
| `cartesian_controller.cpp:447` | 激活时从当前关节/工具姿态初始化参考 | 后续显式切换须重新观测并确认状态 | 源码审计；新平台没有激活它 |
| 同文件 `on_deactivate`、`stop_commands`（203） | deactivate 仅返回成功；stop_commands 跳过写值，不构成已验证的保持/停止程序 | 不把它当独立看门狗或急停 | 真机执行的阻塞项 |
| 同文件目标接收/更新 | 未见基于请求年龄的独立目标超时；进程退出后目标可能留在底层 | 后续必须补齐或选用可证明的执行层超时方案 | 当前禁止 real execute |
| `crisp_controllers_robot_demos/launch/franka.launch.py` | 原完整入口会激活运动控制器，且启动手爪 adapter | 只复用描述/硬件节点生成函数，不执行完整 launch | 新只读 launch 已做语法检查，未启动硬件 |
| `crisp_py_franka_hand_adapter.py:153` | 构造期间 `gripper_client.open()` | 不导入或启动该 adapter | 源码确认；只读路径绕开 |
| `franka_gripper/src/gripper_action_server.cpp:76` | 构造时 readOnce；Move 使用总宽度与速度；joint_state 两手指各为总宽度/2 | 订阅两手指并求和，独立 Move 映射；无 homing 目标 | 真实宽度订阅通过；Move 仅 Mock/映射通过 |
| `franka_hardware/src/robot.cpp:298` 等 | 切入控制接口的异常分支会 automaticErrorRecovery | 真机写入前须审计/约束自动恢复行为 | 阻塞项，未调用恢复 |
| `pose_broadcaster.cpp` | FK 得到 model root 下工具位姿，base_frame 用作 header 标记 | 工具与基座必须对应实际 URDF；平台读取展开 URDF 做只读 FK | 固定链/偏移测试通过；未将改 frame 名当转换 |
| 原仓库 `src/camera_driver/docker-compose.dual-franka.yaml` | 原相机固定两组分辨率及序列号，镜像 latest | 本仓库仅提供新的配置化启动入口，不复制现场 Compose | 现有两路真实压缩图像读取通过；新启动流程未执行 |

## 只读现场结果与缺项

2026-10-30 的 5 秒订阅读到了七关节、夹爪以及主相机 1280×720、腕相机 640×480 的 JPEG。读者节点只发现 `/parameter_events` 发布者，没有控制话题发布者；驱动写入为零。图像 optical frame 与模板一致。

另一次只读 graph 查询中，`/target_pose` 和 `/target_joint` 没有发现发布者，但 `/controller_manager/list_controllers` 请求超时；关节状态发布者名字由 DDS 报为 unknown。不能据此认证当前控制器状态、硬件接口占用或实际 FCI 故障状态。

| 待补信息 | 当前证据/获取方式 |
| --- | --- |
| 机器人 System Version、服务器版本与实际兼容组合 | 到机器人 Desk/系统页面记录，并与官方版本表核对；不能因为源码写 0.19.0 就猜机器人版本 |
| 当前控制器与硬件接口实际状态 | 现场排查 list_controllers 超时，再保存 list_controllers/list_hardware_interfaces 结果 |
| 实时进程权限/调度/网络抖动 | 当前 shell rtprio=0；需在实际运行进程核查 rtprio、memlock、CPU/网卡配置 |
| 机器人 IP、专用网卡、frame 与工具安装 | 从现场有效配置确认；公共模板保留 null，URDF 展开仅用于 FK |
| 相机内外参和标定文件来源/校验 | 记录路径与 SHA；本次图像可用不代表已核实外参 |
| 真机 workspace、允许步长、关节/夹爪限制 | 对照实际 URDF、机器人和现场试验填写，不能用 Mock 范围冒充 |
| 独立目标超时、停止、切换和禁止自动恢复方案 | 源码存在缺口，完成工程实现与现场断线/进程终止测试后才能开放真实执行 |
| 第二台电脑 | 尚未提供或访问；迁移步骤已交付，未声明通过 |

原始环境报告仍保留在原电脑的 `artifacts/franka_platform/`，没有推送到公开仓库。公开只读摘要见[验收报告](acceptance-report.md)；新电脑运行 `collect_environment.sh` 生成自己的完整环境证据。

## 独立 Docker 镜像新增验证

`jiahanyu/franka_fr3` 从固定 digest 的官方 Humble 基镜像构建，未继承上述实验镜像。全部原生控制依赖已按固定源码重新编译，20 个动态库可加载；Python 平台核心、Mock 服务和真实只读订阅通过。Pinocchio/ros2_control 二进制版本及三处构建兼容处理见 [Docker 文档](docker.md)，实际 apt/Python 与原生库哈希保存在镜像内。

真实只读订阅继续使用原运行控制器与相机作为数据源，没有启动新镜像中的硬件插件；新库连接机器人的兼容性、实时执行与第二台物理电脑仍待现场验收。
