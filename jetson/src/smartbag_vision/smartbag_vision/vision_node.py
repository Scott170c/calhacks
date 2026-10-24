"""vision_node: both cameras -> YOLOv8 -> per-camera tracking and rim-crossing -> /smartbag/camera_event.

One process drives both cameras so the GPU runs one model instance (the Nano has 4 GB shared memory).
"""
import json
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String

from .core.camera import LatestFrameCamera
from .core.crossing import CrossingDetector, polygon_from_flat
from .core.detector import MockDetector, make_detector

try:
    from sensor_msgs.msg import CompressedImage
except ImportError:  # pragma: no cover
    CompressedImage = None


class VisionNode(Node):
    def __init__(self):
        super().__init__("vision_node")
        p = self.declare_parameter
        self.cam_names = list(p("cameras", ["cam0", "cam1"]).value)
        width, height, fps = p("width", 1280).value, p("height", 720).value, p("fps", 30).value
        backend = p("detector.backend", "ultralytics").value
        model = p("detector.model", "/opt/smartbag/models/yolov8n.engine").value
        imgsz, conf = p("detector.imgsz", 416).value, p("detector.conf", 0.3).value
        device = p("detector.device", "0").value
        half = p("detector.half", True).value
        labels = [x for x in p("labels", [""]).value if x]
        min_conf, min_area = p("min_conf", 0.35).value, p("min_area", 0.002).value
        confirm, drop = p("confirm_frames", 2).value, p("drop_motion", 0.08).value
        self.rate_hz = float(p("rate_hz", 15.0).value)
        self.debug_hz = float(p("debug_image_hz", 0.0).value)
        mock_script = p("detector.mock_script", "").value

        self.cams, self.crossers = [], []
        for name in self.cam_names:
            src = p(name + ".source", "csi:%d" % len(self.cams)).value
            zone = list(p(name + ".inside_zone", [0.0, 0.4, 1.0, 0.4, 1.0, 1.0, 0.0, 1.0]).value)
            flip = p(name + ".flip", 0).value
            cam = None if src in ("", "none") else LatestFrameCamera(name, src, width, height, fps, flip)
            self.cams.append(cam)
            self.crossers.append(CrossingDetector(name, polygon_from_flat(zone), min_conf=min_conf, min_area=min_area,
                                                  confirm_frames=confirm, drop_motion=drop, labels=labels or None))

        if backend == "mock":
            script = []
            if mock_script:
                with open(mock_script) as f:
                    for e in json.load(f):
                        script.append((e["t"], self.cam_names.index(e["camera"]),
                                       [{"box": tuple(d["box"]), "label": d["label"], "conf": d["conf"]} for d in e["detections"]]))
            self.detector = MockDetector(script)
        else:
            self.get_logger().info("loading %s detector %s (imgsz %d)" % (backend, model, imgsz))
            try:
                self.detector = make_detector(backend, model, imgsz=imgsz, conf=conf, device=device, half=half)
            except Exception as e:  # noqa: BLE001
                self.get_logger().fatal(
                    "could not load the %s model %s: %s. Ultralytics: build the TensorRT engine on this Jetson "
                    "(scripts/export_engine.sh). ONNX: install onnxruntime, or OpenCV >= 4.8 for the OpenCV DNN fallback." % (backend, model, e))
                raise SystemExit(1)

        self.pub_event = self.create_publisher(String, "/smartbag/camera_event", 50)
        self.pub_status = self.create_publisher(String, "/smartbag/vision_status", 10)
        self.pub_debug = []
        if self.debug_hz > 0 and CompressedImage is not None:
            self.pub_debug = [self.create_publisher(CompressedImage, "/smartbag/%s/debug/compressed" % n, qos_profile_sensor_data) for n in self.cam_names]
        self.stats = {"frames": 0, "infer_ms": 0.0, "events": 0, "started": time.time()}
        self.last_seq = [0] * len(self.cams)
        self.last_debug = 0.0
        self.last_dets = [[] for _ in self.cams]
        for cam in self.cams:
            if cam:
                cam.start()
        self.create_timer(1.0, self._status)
        self.stop = threading.Event()
        self.worker = threading.Thread(target=self._loop, name="vision", daemon=True)
        self.worker.start()

    def _loop(self):
        period = 1.0 / max(1.0, self.rate_hz)
        mock = isinstance(self.detector, MockDetector)
        while not self.stop.is_set() and rclpy.ok():
            t0 = time.time()
            frames, idx = [], []
            for i, cam in enumerate(self.cams):
                if mock:
                    frames.append(None); idx.append(i); continue
                if cam is None:
                    continue
                seq, stamp, frame = cam.read()
                if frame is not None and seq != self.last_seq[i]:
                    self.last_seq[i] = seq
                    frames.append(frame); idx.append(i)
            if frames:
                ti = time.time()
                try:
                    results = self.detector.detect(frames, cams=idx) if mock else self.detector.detect(frames)
                except Exception as e:  # noqa: BLE001
                    self.get_logger().error("detector failed: %s" % e)
                    time.sleep(0.5)
                    continue
                dt = (time.time() - ti) * 1000.0
                self.stats["infer_ms"] = 0.9 * self.stats["infer_ms"] + 0.1 * dt if self.stats["frames"] else dt
                now = time.time()
                for i, dets in zip(idx, results):
                    self.stats["frames"] += 1
                    self.last_dets[i] = dets
                    for ev in self.crossers[i].update(dets, now):
                        self.stats["events"] += 1
                        self.pub_event.publish(String(data=json.dumps(ev)))
                        self.get_logger().info("%s %s %s (%.2f, %s)" % (ev["camera"], ev["direction"], ev["label"], ev["conf"], ev["reason"]))
                if self.pub_debug and not mock and now - self.last_debug >= 1.0 / self.debug_hz:
                    self.last_debug = now
                    self._publish_debug(frames, idx)
            time.sleep(max(0.0, period - (time.time() - t0)))

    def _publish_debug(self, frames, idx):
        import cv2
        for frame, i in zip(frames, idx):
            img = frame.copy()
            h, w = img.shape[:2]
            zone = self.crossers[i].zone
            pts = [(int(x * w), int(y * h)) for x, y in zone]
            for a, b in zip(pts, pts[1:] + pts[:1]):
                cv2.line(img, a, b, (74, 101, 232), 2)
            for tr in self.crossers[i].tracker.tracks:
                x1, y1, x2, y2 = tr.box
                cv2.rectangle(img, (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h)), (99, 157, 31), 2)
                cv2.putText(img, "%s #%d" % (tr.label, tr.id), (int(x1 * w), max(12, int(y1 * h) - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (99, 157, 31), 1)
            ok, jpg = cv2.imencode(".jpg", cv2.resize(img, (640, int(640 * h / w))), [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                msg = CompressedImage()
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.header.frame_id = self.cam_names[i]
                msg.format = "jpeg"
                msg.data = jpg.tobytes()
                self.pub_debug[i].publish(msg)

    def _status(self):
        up = time.time() - self.stats["started"]
        cams = []
        for name, cam in zip(self.cam_names, self.cams):
            cams.append({"name": name, "healthy": bool(cam and cam.healthy) or isinstance(self.detector, MockDetector),
                         "error": cam.error if cam else "", "frames": cam.frames if cam else 0})
        self.pub_status.publish(String(data=json.dumps({
            "fps_per_camera": round(self.stats["frames"] / max(1.0, up) / max(1, len(self.cams)), 1),
            "infer_ms": round(self.stats["infer_ms"], 1), "events": self.stats["events"], "cameras": cams})))

    def destroy_node(self):
        self.stop.set()
        for cam in self.cams:
            if cam:
                cam.stop()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = VisionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
