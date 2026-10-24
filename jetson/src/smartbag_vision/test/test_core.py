"""Unit tests for the pure-Python core (no ROS, no camera, no GPU): python3 -m pytest test/"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from smartbag_vision.core.crossing import CrossingDetector, point_in_polygon  # noqa: E402
from smartbag_vision.core.fusion import EventFuser, parse_sku_map  # noqa: E402
from smartbag_vision.core.protocol import add_line, parse_ack, remove_line  # noqa: E402
from smartbag_vision.core.tracker import IouTracker, iou  # noqa: E402
from smartbag_vision.core.transport import SerialEsp32Transport  # noqa: E402

ZONE = [(0.0, 0.4), (1.0, 0.4), (1.0, 1.0), (0.0, 1.0)]   # inside = lower 60%


def det(cx, cy, label="banana", conf=0.8, s=0.12):
    return {"box": (cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2), "label": label, "conf": conf}


def run(cd, path, label="banana", conf=0.8, t0=0.0, dt=0.066):
    evs = []
    for i, (x, y) in enumerate(path):
        evs += cd.update([det(x, y, label, conf)] if y is not None else [], t0 + i * dt)
    return evs


def test_protocol():
    assert add_line("1001", "JA3F0001") == "+1001@JA3F0001"
    assert remove_line("1001") == "-1001"
    assert parse_ack("OK +1005 4.69") == {"kind": "ok_add", "sku": "1005", "price": 4.69, "raw": "OK +1005 4.69"}
    assert parse_ack("ERR 9999 unknown")["kind"] == "err"
    assert parse_ack("PAID 7KQ2XD")["code"] == "7KQ2XD"
    assert parse_ack("hello")["kind"] == "other"


def test_two_items_side_by_side_are_two_tracks():
    cd = CrossingDetector("cam0", ZONE)
    evs = []
    for i, y in enumerate([0.1, 0.25, 0.42, 0.55, 0.65, 0.75]):
        evs += cd.update([det(0.25, y, "banana"), det(0.75, y, "apple")], i * 0.066)
    assert sorted((e["label"], e["direction"]) for e in evs) == [("apple", "add"), ("banana", "add")]


def test_geometry_and_tracker():
    assert point_in_polygon(0.5, 0.7, ZONE) and not point_in_polygon(0.5, 0.2, ZONE)
    assert iou((0, 0, 1, 1), (0, 0, 1, 1)) == 1.0
    tr = IouTracker()
    for i in range(5):
        active, _ = tr.update([det(0.5, 0.1 + 0.1 * i)], i)
    assert len(active) == 1 and active[0].hits == 5      # one track followed a moving box


def test_item_dropped_in_is_one_add():
    cd = CrossingDetector("cam0", ZONE)
    evs = run(cd, [(0.5, 0.10), (0.5, 0.20), (0.5, 0.32), (0.5, 0.48), (0.5, 0.60), (0.5, 0.72), (0.5, 0.80)])
    assert [(e["direction"], e["label"], e["reason"]) for e in evs] == [("add", "banana", "entered")]


def test_item_taken_out_is_one_remove():
    cd = CrossingDetector("cam0", ZONE)
    evs = run(cd, [(0.5, 0.80), (0.5, 0.70), (0.5, 0.55), (0.5, 0.35), (0.5, 0.25), (0.5, 0.15)])
    assert [(e["direction"], e["reason"]) for e in evs] == [("remove", "taken_out")]


def test_hand_brings_item_in_and_pulls_it_back():
    cd = CrossingDetector("cam0", ZONE)
    evs = run(cd, [(0.5, 0.1), (0.5, 0.3), (0.5, 0.5), (0.5, 0.6), (0.5, 0.65), (0.5, 0.5), (0.5, 0.35), (0.5, 0.2), (0.5, 0.1)])
    assert [e["direction"] for e in evs] == ["add", "remove"]


def test_items_already_in_bag_are_ignored():
    cd = CrossingDetector("cam0", ZONE)
    assert run(cd, [(0.3, 0.8)] * 20) == []


def test_fast_drop_seen_only_inside():
    cd = CrossingDetector("cam0", ZONE, drop_motion=0.08)
    evs = run(cd, [(0.5, 0.45), (0.5, 0.58), (0.5, 0.70), (0.5, 0.78), (0.5, 0.80)])
    assert [(e["direction"], e["reason"]) for e in evs] == [("add", "drop")]


def test_jitter_at_the_rim_does_not_double_count():
    cd = CrossingDetector("cam0", ZONE)
    path = [(0.5, 0.2), (0.5, 0.3), (0.5, 0.45), (0.5, 0.38), (0.5, 0.46), (0.5, 0.5), (0.5, 0.55), (0.5, 0.6)]
    assert [e["direction"] for e in run(cd, path)] == ["add"]


def test_low_confidence_and_unknown_labels_filtered():
    cd = CrossingDetector("cam0", ZONE, labels=["banana"])
    path = [(0.5, 0.1), (0.5, 0.3), (0.5, 0.5), (0.5, 0.6), (0.5, 0.7)]
    assert run(cd, path, label="person") == []
    cd2 = CrossingDetector("cam0", ZONE)
    assert run(cd2, path, conf=0.2) == []


class Clock(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def ev(cam, label, direction, conf, t):
    return {"camera": cam, "label": label, "direction": direction, "conf": conf, "t": t, "track": 1, "reason": "x"}


def test_fusion_two_cameras_one_line():
    c = Clock()
    f = EventFuser(["banana=1001", "apple=1003"], clock=c, tag_prefix="JT")
    out = f.push(ev("cam0", "banana", "add", 0.8, c.t))
    out += f.push(ev("cam1", "banana", "add", 0.7, c.t + 0.3))
    c.t += 2
    out += f.flush()
    assert out == ["+1001@JT0001"]
    assert f.inventory == {"1001": 1}


def test_fusion_disagreement_uses_confidence():
    c = Clock()
    f = EventFuser(["banana=1001", "apple=1003"], clock=c, tag_prefix="JT")
    out = f.push(ev("cam0", "apple", "add", 0.4, c.t)) + f.push(ev("cam1", "banana", "add", 0.9, c.t + 0.2))
    assert out == ["+1001@JT0001"]


def test_fusion_single_camera_threshold_and_unknown_sku():
    c = Clock()
    f = EventFuser(["banana=1001"], clock=c, tag_prefix="JT")
    f.push(ev("cam0", "banana", "add", 0.5, c.t))           # too weak for one camera
    f.push(ev("cam1", "person", "add", 0.9, c.t + 5))       # not a product
    c.t += 10
    assert f.flush() == []
    f.push(ev("cam1", "banana", "add", 0.8, c.t))
    c.t += 1
    assert f.flush() == ["+1001@JT0001"]


def test_fusion_never_removes_what_was_not_added():
    c = Clock()
    f = EventFuser(["banana=1001"], clock=c, tag_prefix="JT")
    out = f.push(ev("cam0", "banana", "remove", 0.9, c.t)) + f.push(ev("cam1", "banana", "remove", 0.9, c.t + 0.1))
    assert out == []
    out = f.push(ev("cam0", "banana", "add", 0.9, c.t + 3)) + f.push(ev("cam1", "banana", "add", 0.9, c.t + 3.1))
    out += f.push(ev("cam0", "banana", "remove", 0.9, c.t + 6)) + f.push(ev("cam1", "banana", "remove", 0.9, c.t + 6.1))
    assert out == ["+1001@JT0001", "-1001"] and f.inventory == {}


def test_two_items_close_together_from_one_camera_stay_two():
    c = Clock()
    f = EventFuser(["banana=1001", "apple=1003"], clock=c, tag_prefix="JT")
    out = f.push(ev("cam0", "banana", "add", 0.9, c.t)) + f.push(ev("cam0", "apple", "add", 0.9, c.t + 0.2))
    c.t += 1
    out += f.flush()
    assert sorted(out) == ["+1001@JT0001", "+1003@JT0002"] or sorted(out) == ["+1001@JT0002", "+1003@JT0001"]


def test_sku_map_parsing():
    assert parse_sku_map(["banana=1001", "bad", " apple = 1003 "]) == {"banana": "1001", "apple": "1003"}


class FakeSerial(object):
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.written = []

    def read(self, n):
        import time
        if self.incoming:
            return self.incoming.pop(0)
        time.sleep(0.01)
        return b""

    def write(self, b):
        self.written.append(b.decode())

    def flush(self):
        pass

    def close(self):
        pass


def test_serial_transport_queues_until_phone_connects_and_reads_acks():
    import time
    acks, status = [], []
    fake = FakeSerial([b"SmartBag-01 advertising\n"])
    t = SerialEsp32Transport(serial_factory=lambda: fake, on_ack=acks.append, on_status=status.append)
    time.sleep(0.1)
    t.send("+1001@JT0001")
    time.sleep(0.05)
    assert fake.written == []                         # phone not connected yet: queued
    fake.incoming += [b"phone connected\nphone: OK +1001 1.29\n"]
    time.sleep(0.2)
    assert fake.written == ["+1001@JT0001\n"]
    assert acks == ["OK +1001 1.29"]
    fake.incoming += [b"not connected, dropped: +1003@JT0002\n"]
    time.sleep(0.15)
    assert list(t.queue) == ["+1003@JT0002"]          # ESP32 dropped it: requeued for later
    t.close()
