# 故障定位

诊断输出使用 `PASS / FAIL / SKIP / NOT_RUN`。没有执行检查时不显示 PASS；“没有设备”与“设备存在但读取失败”分别记录。默认 doctor 不探测机器人或启动任何设备。

| 层次/现象 | 检查方法 | 处理与边界 |
| --- | --- | --- |
| 平台 import 失败 | `python --version`、venv 内 `pip check` | Python≥3.10，安装 `franka_platform`，不要把顶层目录命名为 `platform` |
| pip/colcon 的 setuptools 冲突 | 查看 `constraints.txt` 和实际解释器 | 使用已固定 setuptools 79.0.1；构建工具独立于系统 ROS，不升级整个系统 |
| `canonicalize_version(...strip_trailing_zero...)` | 检查 packaging 实际版本 | 此次已复现旧系统 packaging 与新构建工具混用；用固定 packaging 25.0 或直接安装已构建 wheel |
| Mock 意外加载 ROS/模型 | 检查 `PYTHONPATH`、`PYTHONHOME` 和验收 JSON | 默认 bootstrap/Mock 验收清除这两项环境污染；不要安装模型来修复基础平台 |
| ROS 模块不可导入 | 检查 `ROS_DISTRO`、Python ABI、source 的 setup | 当前真实环境是容器 Humble/Python3.10；宿主机 Jazzy/Python3.13 不可替换 |
| 能看到历史 topic 但收不到状态 | 用只读订阅器查看源时间戳、数据年龄；不要只信 daemon 缓存 | 先查真实发布源、Domain、middleware和运行进程；不因此自动重启或激活控制器 |
| controller manager 超时 | 在同一 ROS 环境运行 `doctor.sh --ros`，读取服务/节点列表 | 本次真实查询仍超时；需要现场确认管理器、DDS及进程；禁止把超时当可执行 |
| Ping 可通、FCI 不能读 | 检查专用网卡、路由、FCI模式、机器人状态及匹配版本 | Ping 只证明部分网络连通，不证明实时链路或控制通过 |
| UDP timeout | 查看旧状态发布器日志、接线、机器人模式、丢包/时延 | 不循环重启并自动恢复；采用 [官方故障说明](https://frankarobotics.github.io/docs/troubleshooting.html) 对应版本排查 |
| kernel 名称有 realtime 但无执行资格 | 查 `/sys/kernel/realtime`、实际进程 rtprio、用户组、memlock | 本机当前 shell `ulimit -r=0`；不能仅靠内核名称或容器镜像判定合格 |
| `CAMERA_UNAVAILABLE` | 查看两路 CompressedImage 的实际来源和 USB占用 | 两路必须都存在；不生成替代图或静默改成 robot_only |
| `STALE_CAMERA` / `STALE_STATE` | 比较 source stamp、arrival lag和本地单调年龄 | 排查发布频率、队列和时钟；不能简单扩大阈值冒充可用 |
| `SENSOR_SKEW` | 查观测里的真实时间差和配对策略 | 最近帧配对不是严格同步；先确认采集链路再讨论阈值 |
| 相机 frame 不匹配 | 对照 header.frame_id 与现场配置 optical frame | 只改名字不会改变坐标；配置必须对应真实传感器 |
| TCP位置不合理 | 核对展开 URDF 的 base→tool 链、关节名、工具安装、固定偏移 | 不用法兰位姿直接冒充TCP；重做只读FK核验 |
| `READ_ONLY` / `CONTROL_NOT_OWNED` | 查看 capabilities.permission / writer 状态 | 连接不自动获取写入权；只允许一个当前连接持有会话 |
| `STALE_EPOCH` | 模式切换、停止、重新获取后是否重新取观测 | 重新获取 observation并构造新动作，不重放旧请求 |
| `REQUEST_ID_CONFLICT` | 比较完整信封 | 同一ID只可重发同一内容；改内容必须新ID |
| `DUPLICATE_REFERENCE` | 是否对同一 observation 发送第二条 delta | 重新取得观测，不能靠换ID重复累加 |
| `CONTROL_MODE_MISMATCH` | 查当前模式和动作类型 | 显式切换；服务端不会自动切换 |
| `LIMIT_EXCEEDED` | 查原始请求、换算目标、最新实测状态和现场范围 | 不统一放宽成[-π,π]，不把端点检查当速度/加速度验证 |
| `COMMAND_TIMEOUT` | 查询该 request 的反馈与误差，查看 fault | 已接受不等于完成；先排查，再释放并重新获取，不自动恢复任务 |
| `EXECUTION_NOT_VERIFIED` | 查看源码审计中的 watchdog/stop/switch/恢复缺口 | 真实执行后端尚未开放，无法仅靠配置解锁；需要补齐工程实现与现场测试 |
| 远端收不到图像 | 检查 SSH 转发、SDK版本和 base64 内容 | 服务保持loopback；不返回控制电脑的文件路径代替字节 |

实际诊断命令：

```bash
bash scripts/franka_platform/doctor.sh
PYTHON=.venvs/franka-platform/bin/python bash scripts/franka_platform/doctor.sh \
  --platform-url ws://127.0.0.1:8765
# 以下仅在正确的 Humble 环境中执行；仍不激活控制器
bash scripts/franka_platform/doctor.sh --ros
```

旧源文件或其他实验脚本有硬编码 IP/路径时，不要通过全局替换破坏用户工作；基础平台的现场值只放在本地 YAML 中。控制器、夹爪与源码补丁发生变化后，需要重新采集版本并重做对应验证。
