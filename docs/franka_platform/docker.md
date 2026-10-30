# Docker 镜像部署与发布

目标仓库：`jiahanyu/franka_fr3`。首版为 Linux `amd64` 预览镜像，默认 `mock + read_only`。真机执行适配仍禁用；镜像内原生库的编译通过不等于已完成机器人执行或第二台电脑迁移验收。

## 镜像内容与来源

镜像从固定 digest 的官方 `ros:humble-ros-base-jammy` 构建，不继承原电脑实验容器的文件系统。原生控制依赖按 `SOURCE_BASELINE.json` 的固定源码重新编译，安装于 `/opt/franka-control`；Python 平台位于 `/opt/franka-platform`，使用与 Humble 一致的 Python 3.10 venv。

基镜像固定为 `ros@sha256:a3f4de78e42cca693a543ece5798aedcf1cae0171fe71c334a047332cc72ef93`。本次镜像的 ROS/Pinocchio 二进制依赖与原电脑的旧依赖清单不同；Dockerfile 显式固定 Pinocchio 4.0.0、ros2_control 2.54.3、ros2_controllers 2.54.1 的包版本。实际全量 apt/Python 版本随镜像保存。它没有修改主机或旧控制容器的依赖。

为从不含 Git 元数据的干净构建上下文编译旧源码，`docker/build_control.sh` 包含三处明确的构建兼容处理：libfranka 的 CPack 元数据使用源码固定版本；CRISP 引用 Pinocchio 的公共 `frames.hpp`；CRISP 链接导出的 `pinocchio::pinocchio` 目标以传递 parser 依赖。这些处理不改变控制目标、增益、停止或恢复算法。实际处理记录在镜像 `/opt/franka-image-manifest/native-build.json`。

`.dockerignore` 采用允许列表，只接收平台与固定控制源码；排除 Git 元数据、现场 YAML、凭据、模型权重、旧构建产物及实验目录。构建阶段不连接机器人。运行使用非 root 用户，默认不启动 controller manager、运动控制器、夹爪或恢复程序。

## 拉取和运行

```bash
docker pull jiahanyu/franka_fr3:0.1.0-preview
# 无网络、无硬件的容器内核心验收
docker run --rm --network none --read-only --tmpfs /tmp \
  jiahanyu/franka_fr3:0.1.0-preview self-test
# Linux 主机网络；服务仍只监听 127.0.0.1:8765
docker run --rm --init --network host --read-only --tmpfs /tmp \
  --name franka-fr3-platform \
  --mount type=volume,source=franka-platform-logs,target=/home/platform/run/artifacts \
  jiahanyu/franka_fr3:0.1.0-preview
```

宿主机使用已有 SDK / `read_only_client.py` 连接 `ws://127.0.0.1:8765`。镜像中的 loopback 监听配合 Linux host network；不要以普通 bridge 端口映射代替这里的网络设置。远端仍用 SSH 转发。

安装 Docker Compose 插件后：

```bash
docker compose -f docker/compose.yaml up -d platform
docker compose -f docker/compose.yaml logs platform
docker compose -f docker/compose.yaml stop platform
```

Compose 不自动重启服务。健康检查只确认 RPC 响应，不认证 FCI、控制器或传感器状态。配置自定义固定端口时健康检查会读取相同 YAML；`port: 0` 的临时动态端口用于测试，测试容器单独关闭周期健康检查。

## 真实只读

继续使用现场已有的机器人状态源与相机驱动。运行平台订阅服务不需要重复启动控制器或相机。

1. 将模板复制为 `franka_platform/configs/robot.local.yaml`，保持 `backend: real`、`permission: read_only`，填写实际 topic/frame/Domain/middleware。
2. 依据部署文档生成并核对展开 URDF，保存到 `artifacts/franka_platform/robot.urdf`。
3. 现场 YAML 的 `ros.robot_description_file` 填 **容器内路径** `/run/franka/robot.urdf`。
4. 停止使用同一服务端口的 Mock 平台，再只启动指定服务：

```bash
docker compose -f docker/compose.yaml stop platform
docker compose -f docker/compose.yaml --profile real up -d real-reader
```

Compose 将现场配置及 URDF 以只读 bind mount 提供给服务，源文件不存在时拒绝启动。平台容器不需要 `--privileged`、Docker socket、相机 USB `/dev` 或主机源码目录挂载；两路图像通过现有 ROS 话题获得。相机驱动容器的 USB 访问继续由其已有部署管理。

机器人 IP、相机序列号、标定、照片、原始环境清单和模型权重没有打入镜像。镜像停止仅销毁平台订阅；它不是原机械臂控制器的停止/急停程序。

## 从源码构建和检验

```bash
git clone --recurse-submodules https://github.com/jason-0712/Franka_FR3_Platform.git
cd Franka_FR3_Platform
bash scripts/franka_platform/bootstrap.sh --patches
bash docker/build_image.sh
```

构建脚本先检查全部 vendored 文件哈希、四个顶层和一个递归子模块提交，以及唯一允许的控制描述补丁。源码或补丁不匹配时失败。Docker Engine 需可使用 BuildKit/buildx；不需要升级宿主机 ROS、apt 或内核。

脚本依据 `docker/python-wheels.lock.json` 下载并校验五个官方 PyPI wheel，缓存于本地忽略目录；镜像中的 Python 安装使用 `--no-index`，不依赖容器访问 PyPI。锁文件固定 Python 3.10 / Linux amd64 所需文件与 SHA256；更换目标架构需要另行生成和验证锁文件。

原生构建按顺序编译，限制为两个编译任务；关闭原生单元测试/示例。构建过程在新容器中安装依赖、重新生成所有 native 产物，没有复制旧电脑的 `build/install/log`。`franka_broadcasters` 上游 package.xml 未完整声明 CMake 前置依赖，因此在这些依赖已构建后单独构建。

镜像构建时运行 20 项核心测试；缺少 Git 元数据的补丁恢复测试明确跳过，完整 Git checkout 的 21 项验收单独运行。构建完成后测试实际容器服务：

```bash
bash scripts/franka_platform/bootstrap.sh --python
.venvs/franka-platform/bin/python docker/smoke_image.py
# 显式选择现场只读验证；不发送真实动作
.venvs/franka-platform/bin/python docker/smoke_image.py \
  --real-config franka_platform/configs/robot.local.yaml \
  --robot-description artifacts/franka_platform/robot.urdf
```

Smoke 使用临时容器及随机服务端口，覆盖隔离自测、Mock 只读、三类 Mock 动作和夹爪、dry-run 零写入；可选真实只读状态/双相机与自身 ROS 发布端点检查。完成后只停止本次创建的测试容器。报告在本地 `artifacts/franka_platform/docker/smoke.json`，不会自动上传现场内容。

Smoke 还在无网络容器中逐个加载新编译的原生动态库。可选离线 FK 交叉验证脚本为 `docker/check_fk.py`：将展开 URDF 和本地 `inspect_ros_readonly.py` 生成的 `observation.json` 分别只读挂载为 `/run/franka/robot.urdf`、`/run/franka/observation.json`，通过 `docker run --rm --network none --read-only --tmpfs /tmp -i ... IMAGE python - < docker/check_fk.py` 执行。脚本只输出误差摘要，不发送动作或输出关节样本。

## 发布与版本

先提交构建代码，再用干净提交构建；镜像 OCI revision 保存构建时的 Git 提交。未提交的构建输入会标记 `-dirty`，不用于发布。通过上述检查后显式推送：

```bash
docker push jiahanyu/franka_fr3:0.1.0-preview
```

同时发布对应的 `git-<短提交>` 标签，部署时记录 Docker Hub 返回的 digest。发布清单见 `docker/image-release.json`；其中列出源码提交、平台、镜像 digest、native 构建和实测范围。首次预览发布不设 `latest`。

已发布 `0.1.0-preview` / `git-49f6a90`，两者对应 `sha256:57cabd95e48108b2208ff99f170d698b8842f47dc16c39c71290c635859584ce`。远端 manifest、镜像配置 digest 与源码 revision 已核对，并按该 digest 拉取运行隔离自测通过；[脱敏验证摘要](evidence/docker-preview-summary.json)记录完整测试范围。发布清单和本段说明在上传后提交，镜像内 OCI revision 仍准确指向构建源码提交 `49f6a908ad21d6280f0ede02e3de15bceb47e4c0`。

镜像内可查看：

```bash
docker run --rm --network none jiahanyu/franka_fr3:0.1.0-preview \
  cat /opt/franka-image-manifest/native-build.json
docker run --rm --network none jiahanyu/franka_fr3:0.1.0-preview \
  cat /opt/franka-image-manifest/apt-packages.tsv
```

镜像固定用户空间依赖；主机实时内核、权限、专用网卡、机器人版本兼容及现场 D/E 验收仍按[部署文档](deployment.md)执行。
