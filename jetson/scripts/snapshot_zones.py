#!/usr/bin/env python3
"""Calibrate the bag interior zone of each camera.

Grabs one frame per camera and saves zones_<cam>.jpg with the configured inside_zone drawn on it.
Adjust inside_zone in config/smartbag.yaml until the polygon covers the bag interior and its top
edge sits on the bag rim, then re-run.

    python3 scripts/snapshot_zones.py src/smartbag_vision/config/smartbag.yaml
"""
import sys
import time

import cv2
import yaml

sys.path.insert(0, "src/smartbag_vision")
from smartbag_vision.core.camera import open_capture  # noqa: E402

cfg = yaml.safe_load(open(sys.argv[1] if len(sys.argv) > 1 else "src/smartbag_vision/config/smartbag.yaml"))
v = cfg["vision_node"]["ros__parameters"]
for name in v["cameras"]:
    c = v[name]
    cap, _ = open_capture(c["source"], v.get("width", 1280), v.get("height", 720), v.get("fps", 30), c.get("flip", 0))
    frame = None
    t0 = time.time()
    while time.time() - t0 < 3:
        ok, f = cap.read()
        if ok:
            frame = f
    cap.release()
    if frame is None:
        print("%s: no frame from %s" % (name, c["source"]))
        continue
    h, w = frame.shape[:2]
    z = c["inside_zone"]
    pts = [(int(z[i] * w), int(z[i + 1] * h)) for i in range(0, len(z), 2)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        cv2.line(frame, a, b, (74, 101, 232), 3)
    cv2.putText(frame, "%s inside zone" % name, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (74, 101, 232), 2)
    cv2.imwrite("zones_%s.jpg" % name, frame)
    print("wrote zones_%s.jpg" % name)
