"""Camera capture for the Jetson: CSI ribbon cameras (nvarguscamerasrc), USB/V4L2 cameras, or video files.

A background thread keeps only the newest frame, so inference never works on a stale backlog.
"""
import threading
import time

try:
    import cv2
except ImportError:  # unit tests can run without OpenCV
    cv2 = None


def gst_csi(sensor_id, width, height, fps, flip=0):
    """GStreamer pipeline for a Jetson CSI camera (IMX219/IMX477), converted to BGR for OpenCV."""
    return ("nvarguscamerasrc sensor-id=%d ! video/x-raw(memory:NVMM), width=%d, height=%d, framerate=%d/1, format=NV12 ! "
            "nvvidconv flip-method=%d ! video/x-raw, width=%d, height=%d, format=BGRx ! videoconvert ! video/x-raw, format=BGR ! "
            "appsink drop=true max-buffers=1 sync=false" % (sensor_id, width, height, fps, flip, width, height))


def open_capture(source, width=1280, height=720, fps=30, flip=0):
    """source: 'csi:0' | 'usb:0' | '/dev/video0' | 'file:/path/video.mp4' | 'gst:<pipeline>'."""
    if cv2 is None:
        raise RuntimeError("OpenCV (cv2) is required for camera capture")
    s = str(source)
    if s.startswith("csi:"):
        return cv2.VideoCapture(gst_csi(int(s[4:] or 0), width, height, fps, flip), cv2.CAP_GSTREAMER), False
    if s.startswith("gst:"):
        return cv2.VideoCapture(s[4:], cv2.CAP_GSTREAMER), False
    if s.startswith("file:"):
        return cv2.VideoCapture(s[5:]), True
    dev = int(s[4:]) if s.startswith("usb:") else (int(s) if s.isdigit() else s)
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2) if hasattr(cv2, "CAP_V4L2") else cv2.VideoCapture(dev)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))   # USB2 bandwidth: two cameras need MJPEG
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap, False


class LatestFrameCamera(object):
    def __init__(self, name, source, width=1280, height=720, fps=30, flip=0, loop_files=True):
        self.name = name
        self.source = source
        self.width, self.height, self.fps, self.flip = width, height, fps, flip
        self.loop_files = loop_files
        self._lock = threading.Lock()
        self._frame = None
        self._stamp = 0.0
        self._seq = 0
        self._stop = threading.Event()
        self._thread = None
        self.healthy = False
        self.error = ""
        self.frames = 0

    def start(self):
        self._thread = threading.Thread(target=self._run, name="cam-" + self.name, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def read(self):
        """Returns (seq, stamp, frame) of the newest frame, or (0, 0, None)."""
        with self._lock:
            return self._seq, self._stamp, self._frame

    def _run(self):
        backoff = 0.5
        while not self._stop.is_set():
            try:
                cap, is_file = open_capture(self.source, self.width, self.height, self.fps, self.flip)
            except Exception as e:  # noqa: BLE001
                self.healthy, self.error = False, str(e)
                time.sleep(backoff)
                continue
            if not cap or not cap.isOpened():
                self.healthy, self.error = False, "cannot open %s" % self.source
                time.sleep(backoff)
                backoff = min(5.0, backoff * 2)
                continue
            backoff = 0.5
            period = 1.0 / max(1, self.fps) if is_file else 0.0
            while not self._stop.is_set():
                t0 = time.time()
                ok, frame = cap.read()
                if not ok:
                    if is_file and self.loop_files:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    self.healthy, self.error = False, "camera stopped delivering frames"
                    break
                with self._lock:
                    self._frame, self._stamp = frame, time.time()
                    self._seq += 1
                self.frames += 1
                self.healthy, self.error = True, ""
                if period:  # play files in real time
                    time.sleep(max(0.0, period - (time.time() - t0)))
            cap.release()
