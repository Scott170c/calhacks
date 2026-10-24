#!/bin/bash
# One-time setup on the Jetson (run from the repo root, with your ROS 2 environment sourced).
set -e
sudo apt-get update
sudo apt-get install -y python3-pip python3-serial python3-opencv python3-yaml python3-dbus python3-gi v4l-utils
# Ultralytics needs Python >= 3.8. JetPack 5/6 (Orin, Ubuntu 20.04/22.04): install with pip.
# Original Jetson Nano (JetPack 4.6, Python 3.6): run this package inside the Ultralytics JetPack 4 container
# (docker pull ultralytics/ultralytics:latest-jetson-jetpack4) with ROS 2 in the container, or use the onnx backend.
python3 -m pip install --upgrade pip
python3 -m pip install ultralytics
sudo usermod -aG dialout "$USER"   # serial access to the ESP32 (log out and back in)
colcon build --symlink-install
echo "Next: scripts/export_engine.sh, then: ros2 launch smartbag_vision smartbag.launch.py"
