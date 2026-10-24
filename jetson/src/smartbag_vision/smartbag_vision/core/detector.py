"""Object detectors. All return, per frame, a list of {box: (x1,y1,x2,y2) normalised 0..1, label, conf}.

  ultralytics  YOLOv8 via the ultralytics package: .engine (TensorRT, fastest on Jetson), .onnx or .pt
  onnx         YOLOv8 ONNX export via onnxruntime (or OpenCV DNN), no ultralytics/torch needed
  mock         scripted detections, for tests and for running the pipeline without a GPU
"""
import time

COCO = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
        "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow", "elephant",
        "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
        "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
        "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli",
        "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed", "dining table", "toilet",
        "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
        "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"]


class UltralyticsDetector(object):
    def __init__(self, model_path, imgsz=416, conf=0.3, iou=0.5, device=None, half=True, classes=None):
        from ultralytics import YOLO  # imported lazily: heavy
        self.model = YOLO(model_path, task="detect")
        self.imgsz, self.conf, self.iou = imgsz, conf, iou
        self.device = device
        self.half = half
        self.classes = classes
        names = self.model.names
        self.names = names if isinstance(names, dict) else dict(enumerate(names))

    def warmup(self, frame):
        self.detect([frame])

    def detect(self, frames):
        kw = dict(imgsz=self.imgsz, conf=self.conf, iou=self.iou, verbose=False, half=self.half)
        if self.device is not None:
            kw["device"] = self.device
        if self.classes:
            kw["classes"] = self.classes
        out = []
        for f in frames:  # TensorRT engines are usually built for batch 1
            r = self.model.predict(f, **kw)[0]
            dets = []
            if r.boxes is not None and len(r.boxes):
                for (x1, y1, x2, y2), c, k in zip(r.boxes.xyxyn.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist()):
                    dets.append({"box": (x1, y1, x2, y2), "label": self.names.get(int(k), str(int(k))), "conf": float(c)})
            out.append(dets)
        return out


class OnnxDetector(object):
    """Runs a YOLOv8 ONNX export (output 1 x (4+classes) x anchors) with onnxruntime, else OpenCV DNN."""

    def __init__(self, model_path, imgsz=416, conf=0.3, iou=0.5, names=None):
        import cv2
        import numpy as np
        self.cv2, self.np = cv2, np
        self.imgsz, self.conf, self.iou = imgsz, conf, iou
        self.names = dict(enumerate(names or COCO))
        try:
            import onnxruntime as ort
            providers = [p for p in ("TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
            self.sess = ort.InferenceSession(model_path, providers=providers)
            self.input = self.sess.get_inputs()[0].name
            self.net = None
        except ImportError:
            self.sess = None
            self.net = cv2.dnn.readNetFromONNX(model_path)

    def warmup(self, frame):
        self.detect([frame])

    def _letterbox(self, img):
        h, w = img.shape[:2]
        s = self.imgsz / float(max(h, w))
        nh, nw = int(round(h * s)), int(round(w * s))
        canvas = self.np.full((self.imgsz, self.imgsz, 3), 114, dtype=self.np.uint8)
        top, left = (self.imgsz - nh) // 2, (self.imgsz - nw) // 2
        canvas[top:top + nh, left:left + nw] = self.cv2.resize(img, (nw, nh), interpolation=self.cv2.INTER_LINEAR)
        return canvas, s, left, top

    def detect(self, frames):
        np, cv2 = self.np, self.cv2
        out = []
        for f in frames:
            h, w = f.shape[:2]
            img, s, left, top = self._letterbox(f)
            blob = cv2.dnn.blobFromImage(img, 1 / 255.0, (self.imgsz, self.imgsz), swapRB=True, crop=False)
            if self.sess is not None:
                pred = self.sess.run(None, {self.input: blob})[0]
            else:
                self.net.setInput(blob)
                pred = self.net.forward()
            pred = pred[0].T if pred.shape[1] < pred.shape[2] else pred[0]   # -> anchors x (4+nc)
            scores = pred[:, 4:]
            cls = scores.argmax(1)
            conf = scores[np.arange(len(cls)), cls]
            keep = conf >= self.conf
            pred, cls, conf = pred[keep], cls[keep], conf[keep]
            boxes = []
            for cx, cy, bw, bh in pred[:, :4]:
                x1 = (cx - bw / 2 - left) / s
                y1 = (cy - bh / 2 - top) / s
                boxes.append([float(x1), float(y1), float(bw / s), float(bh / s)])
            idx = cv2.dnn.NMSBoxes(boxes, conf.astype(float).tolist(), self.conf, self.iou) if boxes else []
            dets = []
            for i in (np.array(idx).flatten() if len(idx) else []):
                x, y, bw, bh = boxes[i]
                dets.append({"box": (max(0.0, x / w), max(0.0, y / h), min(1.0, (x + bw) / w), min(1.0, (y + bh) / h)),
                             "label": self.names.get(int(cls[i]), str(int(cls[i]))), "conf": float(conf[i])})
            out.append(dets)
        return out


class MockDetector(object):
    """Replays a script: list of (t_offset_s, camera_index, [detections]); returns the latest per camera."""

    def __init__(self, script=None, clock=time.time):
        self.script = sorted(script or [], key=lambda e: e[0])
        self.clock = clock
        self.t0 = None

    def warmup(self, frame):
        pass

    def detect(self, frames, cams=None):
        if self.t0 is None:
            self.t0 = self.clock()
        dt = self.clock() - self.t0
        out = []
        for i in range(len(frames)):
            cam = cams[i] if cams else i
            cur = []
            for t, c, dets in self.script:
                if t <= dt and c == cam:
                    cur = dets
            out.append(cur)
        return out


def make_detector(backend, model_path=None, imgsz=416, conf=0.3, iou=0.5, device=None, half=True, names=None):
    if backend == "ultralytics":
        return UltralyticsDetector(model_path, imgsz=imgsz, conf=conf, iou=iou, device=device, half=half)
    if backend == "onnx":
        return OnnxDetector(model_path, imgsz=imgsz, conf=conf, iou=iou, names=names)
    if backend == "mock":
        return MockDetector()
    raise ValueError("unknown detector backend %r (use ultralytics, onnx or mock)" % backend)
