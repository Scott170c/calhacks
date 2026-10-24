"""The SmartBag bag protocol (same as the ESP32 firmware and the phone apps).

bag -> phone, newline-terminated:   +1005@TAG  add one (TAG makes repeats idempotent on the server)
                                    -1005      remove one
phone -> bag:                       OK +1005 4.69 | OK -1005 | ERR 9999 unknown | PAID 7KQ2XD
"""
import re

_SKU = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")


def valid_sku(sku):
    return bool(_SKU.match(str(sku)))


def add_line(sku, tag):
    if not valid_sku(sku):
        raise ValueError("bad sku: %r" % (sku,))
    tag = re.sub(r"[^A-Za-z0-9_\-]", "", str(tag))[:40]
    return "+%s@%s" % (sku, tag) if tag else "+%s" % sku


def remove_line(sku):
    if not valid_sku(sku):
        raise ValueError("bad sku: %r" % (sku,))
    return "-%s" % sku


def parse_ack(text):
    """Parse a phone -> bag message. Returns a dict with kind in ok_add, ok_remove, err, paid, other."""
    t = (text or "").strip()
    m = re.match(r"^OK \+(\S+)(?: (\d+(?:\.\d+)?))?$", t)
    if m:
        return {"kind": "ok_add", "sku": m.group(1), "price": float(m.group(2)) if m.group(2) else None, "raw": t}
    m = re.match(r"^OK -(\S+)$", t)
    if m:
        return {"kind": "ok_remove", "sku": m.group(1), "raw": t}
    m = re.match(r"^ERR (\S+)(?: (.*))?$", t)
    if m:
        return {"kind": "err", "sku": m.group(1), "reason": (m.group(2) or "").strip(), "raw": t}
    m = re.match(r"^PAID (\S+)$", t)
    if m:
        return {"kind": "paid", "code": m.group(1), "raw": t}
    return {"kind": "other", "raw": t}
