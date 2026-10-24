"""Fuses events from the two cameras into bag lines.

Both cameras usually see the same item cross the rim. Events with the same direction from
DIFFERENT cameras within `window_s` are one physical event; the label is chosen by confidence.
An event seen by only one camera is accepted after `hold_s` if its confidence is at least
`single_cam_min_conf` (the other camera may have been occluded by a hand).

The fuser keeps a local count per SKU so it never asks to remove something it never added, and
gives each add a unique tag so a retransmitted line is ignored by the server.
"""
import time

from .protocol import add_line, remove_line


def parse_sku_map(entries):
    """["banana=1001", "apple=1003"] or {"banana": "1001"} -> dict."""
    if isinstance(entries, dict):
        return {str(k): str(v) for k, v in entries.items()}
    out = {}
    for e in entries or []:
        if "=" in e:
            k, v = e.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


class EventFuser(object):
    def __init__(self, sku_map, window_s=1.2, hold_s=0.6, single_cam_min_conf=0.55, tag_prefix=None, clock=time.time):
        self.sku_map = parse_sku_map(sku_map)
        self.window_s = window_s
        self.hold_s = hold_s
        self.single_min = single_cam_min_conf
        self.clock = clock
        self.prefix = tag_prefix or ("J%04X" % (int(clock() * 1000) & 0xFFFF))
        self.seq = 0
        self.pending = []          # events waiting for a partner from the other camera
        self.inventory = {}        # sku -> count
        self.log = []              # recent decisions, for status/debugging

    def push(self, ev):
        """Add one camera event. Returns bag lines that are ready now."""
        ready = []
        partner = None
        for p in self.pending:
            if p["camera"] != ev["camera"] and p["direction"] == ev["direction"] and abs(p["t"] - ev["t"]) <= self.window_s and not p.get("paired"):
                if partner is None or abs(p["t"] - ev["t"]) < abs(partner["t"] - ev["t"]):
                    partner = p
        if partner is not None:
            partner["paired"] = True
            self.pending.remove(partner)
            votes = {}
            for e in (partner, ev):
                votes[e["label"]] = votes.get(e["label"], 0.0) + e["conf"]
            label = max(votes.items(), key=lambda kv: kv[1])[0]
            conf = min(1.0, max(partner["conf"], ev["conf"]) + 0.1)
            ready += self._emit(label, ev["direction"], conf, cams=2, t=ev["t"])
        else:
            self.pending.append(dict(ev))
        ready += self.flush()
        return ready

    def flush(self, now=None):
        """Resolve single-camera events whose wait is over. Call regularly."""
        now = self.clock() if now is None else now
        ready = []
        keep = []
        for p in self.pending:
            if now - p["t"] >= self.hold_s:
                if p["conf"] >= self.single_min:
                    ready += self._emit(p["label"], p["direction"], p["conf"], cams=1, t=p["t"])
                else:
                    self._note("skipped", p["label"], p["direction"], "low confidence %.2f, one camera" % p["conf"])
            else:
                keep.append(p)
        self.pending = keep
        return ready

    def _emit(self, label, direction, conf, cams, t):
        sku = self.sku_map.get(label)
        if not sku:
            self._note("skipped", label, direction, "no SKU mapped for this class")
            return []
        if direction == "add":
            self.seq += 1
            self.inventory[sku] = self.inventory.get(sku, 0) + 1
            line = add_line(sku, "%s%04d" % (self.prefix, self.seq))
        else:
            if self.inventory.get(sku, 0) <= 0:
                self._note("skipped", label, direction, "remove ignored: none of this item in the bag")
                return []
            self.inventory[sku] -= 1
            if not self.inventory[sku]:
                del self.inventory[sku]
            line = remove_line(sku)
        self._note("sent", label, direction, "%s (%d camera%s, conf %.2f)" % (line, cams, "" if cams == 1 else "s", conf))
        return [line]

    def reset(self):
        self.inventory = {}
        self.pending = []
        self._note("reset", None, None, "bag paid / cleared")

    def _note(self, what, label, direction, detail):
        self.log.append({"t": self.clock(), "what": what, "label": label, "direction": direction, "detail": detail})
        del self.log[:-50]
