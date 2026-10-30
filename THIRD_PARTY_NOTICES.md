# 第三方源码与来源

本仓库保留已有控制实现。上游许可证及 NOTICE 继续适用于各自目录；此文件不改变上游许可，也不将第三方代码重新授权。

| 路径 | 来源与版本 | 交付方式 |
| --- | --- | --- |
| `src/crisp_controllers` | [utiasDSL/crisp_controllers](https://github.com/utiasDSL/crisp_controllers)，`563842f181ac97cf53d64c96c1788e38ef01611c` | Git submodule |
| `src/crisp_controllers_demos` | [utiasDSL/crisp_controllers_demos](https://github.com/utiasDSL/crisp_controllers_demos)，`d12b9adb9161a6078b36da3bd93fa8e8422572e4` | Git submodule + 一个硬件描述兼容补丁 |
| `src/franka_broadcasters` | [danielsanjosepro/franka_broadcasters](https://github.com/danielsanjosepro/franka_broadcasters)，`f148ae178c94e7b7037fdb7e7044e1c70a92aa80` | Git submodule |
| `src/libfranka` | [frankarobotics/libfranka](https://github.com/frankarobotics/libfranka)，`4df37dd2b527f41ef34b76d6d4d3805864b09993` | Git submodule；递归固定 `common` |
| `src/franka_ros2` | 原 [jason-0712/franka_ws](https://github.com/jason-0712/franka_ws) 提交 `e4ae615688d3f7b69748fb866b220c354fdf0ea8` 中的跟踪源码 | 原样 vendored；保留 LICENSE / NOTICE |
| `src/franka_description` | 同一原仓库提交中的跟踪源码 | 原样 vendored；保留 LICENSE / NOTICE 和网格文件 |

详细文件哈希及 `libfranka/common` 提交见 [SOURCE_BASELINE.json](SOURCE_BASELINE.json)。保留当前已审计控制栈，不将它替换成未经核对的上游最新分支。Franka 目录自身的说明保留其上游历史与适用范围；平台操作以本仓库中文部署文档为入口。

补丁只加入 `fr3.ros2_control.urdf.xacro` 中已有运行环境使用的 `version=0.0.0` 兼容字段；它不是机器人 System Version 的声明。原实验仓库中的夹爪 adapter、Dockerfile 和其他实验 launch 改动不属于这个补丁。平台只读入口不会启动 adapter 或运动控制器。
