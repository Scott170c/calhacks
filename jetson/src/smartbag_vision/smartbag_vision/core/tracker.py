"""Small IoU tracker. Dependency-free, deterministic, fast enough for a handful of boxes per frame."""


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


class Track(object):
    __slots__ = ("id", "box", "hits", "misses", "history", "votes", "born", "last_seen", "state")

    def __init__(self, tid, det, t):
        self.id = tid
        self.box = det["box"]
        self.hits = 1
        self.misses = 0
        self.history = [(t, center(det["box"]))]
        self.votes = {}
        self.vote(det)
        self.born = t
        self.last_seen = t
        self.state = {}          # free-form storage for the crossing logic

    def vote(self, det):
        self.votes[det["label"]] = self.votes.get(det["label"], 0.0) + det["conf"]

    @property
    def label(self):
        return max(self.votes.items(), key=lambda kv: kv[1])[0] if self.votes else None

    @property
    def confidence(self):
        total = sum(self.votes.values())
        return (self.votes.get(self.label, 0.0) / self.hits) if self.hits else 0.0 if total else 0.0


class IouTracker(object):
    """Greedy IoU matching with a centre-distance fallback for small, fast-moving objects."""

    def __init__(self, iou_threshold=0.25, max_center_jump=0.30, max_misses=6, history=30):
        self.iou_threshold = iou_threshold
        self.max_center_jump = max_center_jump
        self.max_misses = max_misses
        self.history_len = history
        self.tracks = []
        self._next = 1

    def update(self, detections, t):
        """detections: list of {box: (x1,y1,x2,y2) normalised 0..1, label, conf}. Returns (active, ended)."""
        pairs = []
        for ti, tr in enumerate(self.tracks):
            for di, d in enumerate(detections):
                score = iou(tr.box, d["box"])
                if score < self.iou_threshold:
                    (cx, cy), (dx, dy) = center(tr.box), center(d["box"])
                    jump = ((cx - dx) ** 2 + (cy - dy) ** 2) ** 0.5
                    if jump > self.max_center_jump:
                        continue
                    score = 0.01 * (1.0 - jump / self.max_center_jump)   # weak match, below any real IoU match
                if tr.label is not None and d["label"] != tr.label:
                    score *= 0.5                                           # prefer same-class matches
                pairs.append((score, ti, di))
        pairs.sort(reverse=True)
        used_t, used_d = set(), set()
        for score, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            tr, d = self.tracks[ti], detections[di]
            tr.box = d["box"]
            tr.hits += 1
            tr.misses = 0
            tr.last_seen = t
            tr.vote(d)
            tr.history.append((t, center(d["box"])))
            if len(tr.history) > self.history_len:
                tr.history.pop(0)
        for ti, tr in enumerate(self.tracks):
            if ti not in used_t:
                tr.misses += 1
        for di, d in enumerate(detections):
            if di not in used_d:
                self.tracks.append(Track(self._next, d, t))
                self._next += 1
        ended = [tr for tr in self.tracks if tr.misses > self.max_misses]
        self.tracks = [tr for tr in self.tracks if tr.misses <= self.max_misses]
        return self.tracks, ended
