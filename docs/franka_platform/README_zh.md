# Franka 基础平台 v0.1

本平台复用工作区已有的 CRISP / Franka 控制栈，提供与学习模型无关的三种目标接口、独立夹爪宽度接口、WebSocket 服务和异步 Python SDK。协议与 Mock 已实现；真实 ROS 后端提供订阅及 dry-run 消息映射。

第一版支持末端绝对位姿、相对于指定观测的基座系末端增量。

## 从这里开始

在工作区根目录运行，Python 需为 3.10 或更新版本：

```bash
git clone --recurse-submodules https://github.com/jason-0712/Franka_FR3_Platform.git
cd Franka_FR3_Platform
bash scripts/franka_platform/bootstrap.sh --plan
bash scripts/franka_platform/bootstrap.sh --python
bash scripts/franka_platform/run_acceptance.sh --mock
```

验收写入 `artifacts/franka_platform/acceptance_mock.json`。它包含数学语义、三类动作及夹爪、网络往返、幂等、断线、超时、权限、反馈完成判定和补丁恢复测试。Mock 不证明真实控制性能。

启动默认的 `mock + read_only` 服务：

```bash
bash scripts/franka_platform/start_platform.sh
```

另一终端仅读取状态及实际传输的图像字节：

```bash
.venvs/franka-platform/bin/python franka_platform/examples/read_only_client.py \
  --output artifacts/franka_platform/mock_observation
```

停止上述服务后，运行确定性 Mock 动作示例：

```bash
# 终端 1；只对 Mock 后端启用执行
bash scripts/franka_platform/start_platform.sh --permission execute
# 终端 2
.venvs/franka-platform/bin/python franka_platform/examples/mock_actions.py
```

相同示例也可针对 `--permission dry_run` 服务运行，此时只返回 `validated`，驱动写入为零。Ctrl-C 关闭本平台服务，不会启动原工作区的其他入口。

## 文档与证据

| 文档 | 内容 |
| --- | --- |
| [源码审计](source-audit.md) | 实际控制链路、启动副作用、固定版本、现场缺项 |
| [架构](architecture.md) | 服务、缓存、会话、后端、进程和失败边界 |
| [协议 v1](interface-v1.md) | 三种动作、旋转与工具变换、SDK、错误与状态 |
| [部署](deployment.md) | 环境固定、安装、只读启动、相机、迁移步骤 |
| [Docker](docker.md) | 官方 ROS 基镜像、固定源码构建、只读运行及发布 |
| [故障定位](troubleshooting.md) | 环境、网络、ROS、控制器、相机、协议 |
| [验收报告](acceptance-report.md) | 本次实际结果、证据、真机执行与换机缺项 |



