"""Explicit read-only hardware startup using audited existing descriptions.

Starts only joint_state_broadcaster and the standard gripper state driver.
Never launches CRISP hand adapter, trajectory/impedance controllers, or recovery.
"""
import importlib.util
import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration, TextSubstitution
from launch_ros.actions import Node


def prepare(context):
    # This launch is executed with the workspace's ROS Python, not the SDK venv.
    import yaml
    cfg = yaml.safe_load(Path(LaunchConfiguration("config").perform(context)).read_text())
    if cfg.get("backend") != "real" or cfg.get("permission") != "read_only":
        raise RuntimeError("Hardware observation launch requires real + read_only configuration")
    if not cfg.get("robot", {}).get("ip"):
        raise RuntimeError("robot.ip must be supplied from the actual installation")
    if cfg.get("ros", {}).get("namespace", ""):
        raise RuntimeError("This audited hardware helper supports the empty namespace only")
    if os.environ.get("ROS_DISTRO") != "humble":
        raise RuntimeError("Require ROS 2 Humble")
    if os.environ.get("ROS_DOMAIN_ID", "0") != str(cfg["ros"]["domain_id"]):
        raise RuntimeError("ROS_DOMAIN_ID differs from configuration")
    # Discovery only; refuses a second manager even if its service is unresponsive.
    import rclpy
    rclpy.init()
    probe = rclpy.create_node("franka_platform_startup_probe", enable_rosout=False,
                             start_parameter_services=False)
    try:
        import time
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            rclpy.spin_once(probe, timeout_sec=.1)
        services = [name for name, _ in probe.get_service_names_and_types()]
        nodes = probe.get_node_names()
        if cfg["ros"]["controller_manager"].rstrip('/')+"/list_controllers" in services or "controller_manager" in nodes:
            raise RuntimeError("An existing controller manager was discovered; attach the reader instead")
    finally:
        probe.destroy_node()
        rclpy.shutdown()
    share = Path(get_package_share_directory("crisp_controllers_robot_demos"))
    spec = importlib.util.spec_from_file_location("franka_platform_audited_hardware", share/"launch/franka.launch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    params = (cfg["robot"]["ip"], "fr3", "false", "false", "true", "", "false")
    hardware = module.robot_description_dependent_nodes_spawner(context, *(TextSubstitution(text=v) for v in params))
    gripper_config = Path(get_package_share_directory("franka_gripper"))/"config/franka_gripper_node.yaml"
    return [*hardware,
            Node(package="controller_manager", executable="spawner", arguments=["joint_state_broadcaster"], output="screen"),
            Node(package="franka_gripper", executable="franka_gripper_node", name="franka_gripper", output="screen",
                 parameters=[{"robot_ip": cfg["robot"]["ip"], "joint_names": cfg["ros"]["finger_joint_names"]},
                             str(gripper_config)])]


def generate_launch_description():
    return LaunchDescription([DeclareLaunchArgument("config"), OpaqueFunction(function=prepare)])
