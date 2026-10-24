"""Turns tracked boxes from ONE camera into bag events.

Each camera is clipped to the bag rim and looks into the bag. In its image, the region where the
bag's interior is visible is the "inside zone" (a polygon in normalised coordinates).

  ADD     a track that started OUTSIDE the zone (hand bringing an item in) and is then seen INSIDE
          for `confirm_frames` consecutive frames.
  ADD     ("drop") a track born inside, near the rim, that then moved at least `drop_motion` deeper
          into the bag: an item dropped in so fast that no frame caught it above the rim.
  REMOVE  a track that started INSIDE and is then seen OUTSIDE for `confirm_frames` frames.
          A track that was added and then leaves again (item pulled back out) cancels its add.

Stationary tracks born inside are items already in the bag; they never produce events.
"""
from .tracker import IouTracker, center


def point_in_polygon(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def _on_border(a, b, eps=1e-6):
    """True when edge a-b lies along the image border (that edge is the frame, not the bag rim)."""
    for k in (0, 1):
        for v in (0.0, 1.0):
            if abs(a[k] - v) < eps and abs(b[k] - v) < eps:
                return True
    return False


def rim_distance(x, y, poly):
    """Distance from a point to the bag rim: the zone edges that are not along the image border."""
    best = None
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if _on_border(a, b):
            continue
        d = _seg_dist(x, y, a[0], a[1], b[0], b[1])
        best = d if best is None else min(best, d)
    return best if best is not None else 1.0


def polygon_from_flat(flat):
    pts = list(flat)
    if len(pts) < 6 or len(pts) % 2:
        raise ValueError("inside_zone needs at least 3 points as a flat list x1,y1,x2,y2,...")
    return [(float(pts[i]), float(pts[i + 1])) for i in range(0, len(pts), 2)]


class CrossingDetector(object):
    def __init__(self, camera, inside_zone, min_conf=0.35, min_area=0.002, confirm_frames=2,
                 drop_motion=0.08, labels=None, tracker=None, drop_rim_band=0.15):
        self.camera = camera
        self.zone = inside_zone if isinstance(inside_zone[0], (tuple, list)) else polygon_from_flat(inside_zone)
        self.min_conf = min_conf
        self.min_area = min_area
        self.confirm = max(1, int(confirm_frames))
        self.drop_motion = drop_motion
        self.drop_rim_band = drop_rim_band   # a "drop" must first appear within this distance of the rim
        self.labels = set(labels) if labels else None
        self.tracker = tracker or IouTracker()

    def is_inside(self, box):
        cx, cy = center(box)
        return point_in_polygon(cx, cy, self.zone)

    def _keep(self, d):
        b = d["box"]
        if d["conf"] < self.min_conf:
            return False
        if (b[2] - b[0]) * (b[3] - b[1]) < self.min_area:
            return False
        return self.labels is None or d["label"] in self.labels

    def update(self, detections, t):
        """Feed one frame of detections (normalised boxes). Returns a list of event dicts."""
        dets = [d for d in detections if self._keep(d)]
        active, ended = self.tracker.update(dets, t)
        events = []
        for tr in active:
            if tr.misses:
                continue
            s = tr.state
            inside = self.is_inside(tr.box)
            if "origin" not in s:
                s["origin"] = "inside" if inside else "outside"
                s["side"] = s["origin"]
                s["streak"] = 0
                s["start"] = center(tr.box)
                s["rim0"] = rim_distance(s["start"][0], s["start"][1], self.zone)
                s["counted"] = None
                continue
            here = "inside" if inside else "outside"
            if here != s["side"]:
                s["streak"] = s["streak"] + 1 if s.get("pending") == here else 1
                s["pending"] = here
                if s["streak"] >= self.confirm:
                    s["side"] = here
                    s["streak"] = 0
                    s.pop("pending", None)
                    ev = self._on_cross(tr, here, t)
                    if ev:
                        events.append(ev)
            else:
                s["streak"] = 0
                s.pop("pending", None)
                # a fast drop: born inside, moved a lot, never crossed
                if s["origin"] == "inside" and s["counted"] is None and here == "inside" and tr.hits >= self.confirm + 1:
                    sx, sy = s["start"]
                    cx, cy = center(tr.box)
                    deeper = rim_distance(cx, cy, self.zone) - s["rim0"]
                    near_rim = s["rim0"] <= self.drop_rim_band
                    if (near_rim and deeper >= self.drop_motion * 0.6 and s.get("moving_in", True)
                            and ((cx - sx) ** 2 + (cy - sy) ** 2) ** 0.5 >= self.drop_motion):
                        s["counted"] = "add"
                        events.append(self._event(tr, "add", t, reason="drop"))
                    elif tr.hits > self.confirm + 4:
                        s["moving_in"] = False   # settled without moving: it was already in the bag
        return events

    def _on_cross(self, tr, here, t):
        s = tr.state
        if here == "inside":
            if s["counted"] == "remove":           # taken out, then put back
                s["counted"] = None
                return self._event(tr, "add", t, reason="returned")
            if s["counted"] is None and s["origin"] == "outside":
                s["counted"] = "add"
                return self._event(tr, "add", t, reason="entered")
        else:
            if s["counted"] == "add":              # brought in, then pulled back out
                s["counted"] = None
                return self._event(tr, "remove", t, reason="pulled_back")
            if s["counted"] is None and s["origin"] == "inside":
                s["counted"] = "remove"
                return self._event(tr, "remove", t, reason="taken_out")
        return None

    def _event(self, tr, direction, t, reason):
        return {"camera": self.camera, "label": tr.label, "direction": direction, "conf": round(tr.confidence, 3),
                "track": tr.id, "t": t, "reason": reason}
