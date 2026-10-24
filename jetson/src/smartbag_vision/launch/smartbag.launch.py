"""Start the SmartBag pipeline: vision (2 cameras + YOLOv8) -> fusion -> BLE bridge.

    ros2 launch smartbag_vision smartbag.launch.py
    ros2 launch smartbag_vision smartbag.launch.py transport:=stdout config:=/path/to/my.yaml
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    default_cfg = os.path.join(get_package_share_directory("smartbag_vision"), "config", "smartbag.yaml")
    cfg = LaunchConfiguration("config")
    return LaunchDescription([
        DeclareLaunchArgument("config", default_value=default_cfg, description="parameter file"),
        DeclareLaunchArgument("transport", default_value="serial", description="serial (ESP32), bluez or stdout"),
        Node(package="smartbag_vision", executable="vision_node", name="vision_node", parameters=[cfg], output="screen", respawn=True, respawn_delay=2.0),
        Node(package="smartbag_vision", executable="fusion_node", name="fusion_node", parameters=[cfg], output="screen", respawn=True, respawn_delay=2.0),
        Node(package="smartbag_vision", executable="ble_bridge_node", name="ble_bridge_node",
             parameters=[cfg, {"transport": LaunchConfiguration("transport")}], output="screen", respawn=True, respawn_delay=2.0),
    ])
