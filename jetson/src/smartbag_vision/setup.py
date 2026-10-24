from glob import glob

from setuptools import find_packages, setup

package_name = "smartbag_vision"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.py")),
        ("share/" + package_name + "/config", glob("config/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Scott Chiang",
    maintainer_email="scottchiang7@gmail.com",
    description="SmartBag on-bag vision: two cameras, YOLOv8, rim-crossing detection and BLE bag lines.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "vision_node = smartbag_vision.vision_node:main",
            "fusion_node = smartbag_vision.fusion_node:main",
            "ble_bridge_node = smartbag_vision.ble_bridge_node:main",
        ],
    },
)
