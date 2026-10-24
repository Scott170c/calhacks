#!/bin/bash
# Build the YOLOv8 TensorRT engine ON THE JETSON (engines are specific to the GPU and TensorRT version).
#   scripts/export_engine.sh [weights.pt] [imgsz]
set -e
WEIGHTS=${1:-yolov8n.pt}
IMGSZ=${2:-416}
mkdir -p /opt/smartbag/models 2>/dev/null || sudo mkdir -p /opt/smartbag/models && sudo chown "$USER" /opt/smartbag/models
cd /opt/smartbag/models
yolo export model="$WEIGHTS" format=engine imgsz="$IMGSZ" half=True device=0 workspace=1
ls -la /opt/smartbag/models
echo "Set detector.model in config/smartbag.yaml to /opt/smartbag/models/$(basename "${WEIGHTS%.*}").engine"
