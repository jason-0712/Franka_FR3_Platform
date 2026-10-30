# 协议 v1

所有 RPC 与动作使用 `schema_version: 1`。单位固定为米、弧度、秒；拒绝模型归一化数组、NaN/Inf、重复 JSON 字段、额外或缺失字段、错误维度及未支持的动作类型。四元数采用 xyzw，范数与 1 相差不超过 `1e-3` 时才规范化；零范数和明显异常值拒绝。

## 传输

固定一种 WebSocket 文本 JSON 协议，默认 `ws://127.0.0.1:8765`。不使用 pickle。请求示例：

```json
{"schema_version":1,"rpc_id":"rpc-unique","method":"get_observation","params":{}}
```

成功响应为 `schema_version/rpc_id/ok:true/result`，失败为 `schema_version/rpc_id/ok:false/error:{code,message}`。图片在观测的 `data_base64` 字段中携带 JPEG 或 PNG 字节，附编码、尺寸、frame、可用性和源时间戳。不是本地路径。

## 动作信封

```json
{
  "schema_version": 1,
  "request_id": "unique-request-id",
  "session_id": "server-issued-session",
  "control_epoch": 2,
  "observation_id": "server-issued-observation",
  "type": "cartesian_absolute",
  "payload": {
    "frame": "base",
    "tool_frame": "fr3_hand_tcp",
    "position_m": [0.405, 0.0, 0.4],
    "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0]
  }
}
```

上述数值仅用于 Mock。现场参数、workspace、关节限制和工具变换必须来自本机核实配置。客户端不能提供自己的观测时刻或扩大动作有效期；所有动作均绑定缓存观测并与最新测得状态比较。

| type | payload | 所需模式 |
| --- | --- | --- |
| `cartesian_absolute` | `frame, tool_frame, position_m[3], quaternion_xyzw[4]` | `cartesian` |
| `cartesian_delta` | `frame, tool_frame, translation_m[3], delta_quaternion_xyzw[4]` | `cartesian` |
| `joint_absolute` | `joint_names[7], positions_rad[7]` | `joint` |
| `gripper_width` | `width_m` | 已显式选取任一种手臂模式；独立请求 |

关节名必须与配置顺序完全相等，不按数组长度猜类型。速度控制、力矩、IK、动作块、工具系增量均未提供。夹爪不藏在手臂数组的最后一维。

## 旋转与工具变换

`R_base_tool` 把工具坐标向量映射到基座。对信封引用观测中的 `(p_ref, q_ref)`，基座系增量固定为：

```text
p_target = p_ref + delta_translation_base
q_target = q_delta_base * q_ref
```

改变朝向不会额外旋转工具的位置；不是直接把整个增量 SE(3) 左乘原位姿。非交换旋转、非单位参考姿态和指定观测参考均有测试。相同相对动作重发不重复累加，同一观测换 request ID 也不能再次消费。

固定变换配置描述 `T_controller_tool`，把 tool 向量映射到控制器受控 frame：

```text
T_base_controller = T_base_tool * inverse(T_controller_tool)
```

即 `q_bc=q_bt*inverse(q_ct)`、`p_bc=p_bt-R_bc*p_ct`。测试含非零 TCP 偏移与非零固定旋转。真实控制器忽略 `PoseStamped.header.frame_id`，所以平台必须先保证坐标语义一致；仅改 frame 字符串没有转换效果。

纯 ROS 映射结果为 `PoseStamped`、按固定顺序的 `JointState(position, velocity=0)`、以及指定总开口宽度与速度的 `franka_msgs/action/Move`。映射通过单测，当前 ROS 后端不会发布这些内容。

## SDK

API 均为异步，连接不自动获取写入权：

```python
from franka_platform.client import Client

async with Client("ws://127.0.0.1:8765") as client:
    capabilities = await client.get_capabilities()
    status = await client.get_status()
    await client.acquire_control()
    await client.set_control_mode("cartesian")
    observation = await client.get_observation()  # 切换后重新取
    action = client.action("cartesian_delta", {
        "frame": capabilities["base_frame_id"],
        "tool_frame": capabilities["tool_frame_id"],
        "translation_m": [0.005, 0, 0],
        "delta_quaternion_xyzw": [0, 0, 0, 1],
    }, observation)
    result = await client.send_action(action)
    result = await client.get_command_status(action["request_id"])
    # 等待手臂目标结束后，才能提交下一独立目标。
    await client.stop()
    await client.release_control()
```

独立夹爪接口为 `await client.set_gripper(width_m)`，可选显式 observation 与 request ID。SDK 获取观测不会 homing 或开合；不调用夹爪接口就不改变夹爪。v1 不承诺手臂与夹爪原子同步。

底层 RPC 方法还包括 `heartbeat`；`set_gripper()` 在同一协议内转换为 `gripper_width` 动作，没有第二种传输。`close()` 关闭连接并停止心跳；服务端释放租约和旧目标。

## 观测与能力

观测包括服务端 observation ID、epoch、单调时刻、原始 ROS 时间戳及其来源，七关节位置/速度、按展开 URDF 得到的 TCP 姿态、夹爪宽度/时间戳、状态、两路图像和 freshness。原始时钟不被假定与远端客户端同步。

状态或图像缺失会返回明确的不可用字段与 `freshness.action_blocker`，不会填充 Mock 数据。`robot_only` 和 `dual_camera` 是不同配置。`get_capabilities()` 分别报告协议实现、当前可执行性和硬件验证状态；Mock 永不把 `hardware_verified` 标成 true。

## 状态和错误

`validated` 是 dry-run 校验完成；`accepted` 是后端接收；`executing` 为等待反馈；`completed` 为反馈达到容差；`rejected` 为拒绝；`aborted` 为接受后被停止、失效或超时。发布消息不能等同到达目标。

| 错误码 | 含义 |
| --- | --- |
| `INVALID_ACTION` / `UNSUPPORTED_ACTION` | 字段、维度、有限值、四元数或动作类型错误 |
| `FRAME_MISMATCH` | 未配置的 base/tool 或工具系增量 |
| `STALE_OBSERVATION` / `STALE_EPOCH` | 观测过期、被淘汰或控制代次已改变 |
| `STALE_STATE` / `STALE_CAMERA` / `SENSOR_SKEW` | 实测状态/图片过期或配对时间差过大 |
| `CAMERA_UNAVAILABLE` | 双相机数据缺失 |
| `DUPLICATE_REFERENCE` | 相对动作重复消费观测 |
| `REQUEST_ID_CONFLICT` | 相同 request ID 使用不同信封 |
| `CONTROL_NOT_OWNED` / `READ_ONLY` | 没有写入权或服务只读 |
| `CONTROL_MODE_MISMATCH` | 必须显式选正确模式 |
| `LIMIT_EXCEEDED` | 目标范围或与最新实测状态的差异超限 |
| `COMMAND_IN_PROGRESS` | v1 不接受目标队列 |
| `ROBOT_NOT_READY` / `CONTROLLER_SWITCH_FAILED` | 状态无效或后端切换失败 |
| `COMMAND_TIMEOUT` / `LEASE_EXPIRED` | 反馈不收敛或写入租约过期 |
| `EXECUTION_NOT_VERIFIED` | 真实执行后端尚不可启用 |

失效、释放或模式切换后的旧动作不会重放。重新获取控制权会归档日志、清空当前会话内存记录；历史 `get_command_status` 可能返回 `UNKNOWN_COMMAND`，日志保留原结果。
