# Franka FR3 Platform

这个仓库包含了模型无关的 Franka FR3 基础平台：观测、三类目标接口、独立夹爪、WebSocket 服务与 Python SDK。

## 安装和验证

纯 Python Mock 使用 Python 3.10+，无需 ROS、CUDA、PyTorch 或模型权重：

```bash
git clone --recurse-submodules https://github.com/jason-0712/Franka_FR3_Platform.git
cd Franka_FR3_Platform
bash scripts/franka_platform/bootstrap.sh --python
bash scripts/franka_platform/run_acceptance.sh --mock
bash scripts/franka_platform/start_platform.sh
```

另一终端读取观测和图像：

```bash
.venvs/franka-platform/bin/python franka_platform/examples/read_only_client.py
```

若只需要轻量 SDK/Mock，可普通 clone 后安装；固定补丁恢复测试需要控制依赖已 checkout。完整部署请使用上面的递归 clone，且不要直接运行上游示例的完整硬件 launch。

## 接口范围

| 接口 | 含义 |
| --- | --- |
| `cartesian_absolute` | 基座系工具绝对位置和 xyzw 四元数 |
| `cartesian_delta` | 相对于指定观测的基座系平移/旋转增量 |
| `joint_absolute` | 配置顺序的七关节绝对角度，无 IK |
| `set_gripper(width_m)` | 独立的夹爪总开口宽度 |

## 仓库内容

- `franka_platform/`：独立 Python 包、配置模板、客户端示例和测试。
- `scripts/franka_platform/`：安装、诊断、只读启动、环境采集及源码导出。
- `src/`：固定版本的 CRISP / Franka 控制依赖和机器人描述。
- `patches/nested_repos/`：平台必需的控制描述兼容补丁。
- `docs/franka_platform/`：中文协议、源码审计、部署及验收报告。
- `SOURCE_BASELINE.json`：原始源码基线、依赖提交、vendored 文件和补丁 SHA256。。

## 文档

[使用说明](docs/franka_platform/README_zh.md) · [接口 v1](docs/franka_platform/interface-v1.md) · [部署与迁移](docs/franka_platform/deployment.md) · [验收报告](docs/franka_platform/acceptance-report.md) · [第三方来源](THIRD_PARTY_NOTICES.md)

Docker Hub 发布仓库为 [`jiahanyu/franka_fr3`](https://hub.docker.com/r/jiahanyu/franka_fr3)。预览镜像默认只读；构建、拉取、Compose、现场配置挂载和验证方法见 [Docker 部署](docs/franka_platform/docker.md)。

现场配置复制自 `robot.example.yaml` 并保存为 `robot.local.yaml`；现场 IP、校准、照片、原始日志及构建产物不进入版本库。机器人实时环境、工具安装、独立 watchdog 和停止/切换流程仍需按验收报告完成。
