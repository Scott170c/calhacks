"""SmartBag walk-out load test against a live SpacetimeDB database.

Each simulated phone opens its own WebSocket (v2.bsatn.spacetimedb), exactly like the Android/iOS apps, and does a
full trip: set payment -> enter a store -> N bag reads -> two fixes outside -> checks it was charged once, correctly.

Seed synthetic stores first (admin token required; stores are named lt-0 .. lt-N):
    python walkout_load.py --seed 2000 --admin-token $SPACETIME_TOKEN
Run:
    python walkout_load.py --shoppers 300
Clean up:
    python walkout_load.py --clear --admin-token $SPACETIME_TOKEN

pip install httpx websockets requests
"""
import argparse, asyncio, json, random, struct, time, uuid
import httpx, requests, websockets

HOST = "https://maincloud.spacetimedb.com"
DB = "smartcart-5dt35"
CENTER = (37.7749, -122.4194)  # load-test grid centre (San Francisco)


def s(v):
    b = v.encode()
    return struct.pack("<I", len(b)) + b


class R:
    def __init__(self, b):
        self.b, self.o = b, 0
    def u8(self): v = self.b[self.o]; self.o += 1; return v
    def u32(self): v = struct.unpack_from("<I", self.b, self.o)[0]; self.o += 4; return v
    def u64(self): v = struct.unpack_from("<Q", self.b, self.o)[0]; self.o += 8; return v
    def i64(self): v = struct.unpack_from("<q", self.b, self.o)[0]; self.o += 8; return v
    def raw(self, n): v = self.b[self.o:self.o + n]; self.o += n; return v
    def str(self): return self.raw(self.u32()).decode()
    def bytes(self): return self.raw(self.u32())


def call_procedure(req, name, args):  # ClientMessage::CallProcedure (tag 4)
    return bytes([4]) + struct.pack("<I", req) + bytes([0]) + s(name) + struct.pack("<I", len(args)) + args


def cart_state(b):
    r = R(b)
    d = dict(storeId=r.str(), storeName=r.str(), addr=r.str(), dist=r.u32(), nearest=r.str(), nearestM=r.u32(), bag=r.str(),
             payment=r.str(), leaving=bool(r.u8()), total=r.u32(), count=r.u32())
    d["lines"] = [(r.str(), r.str(), r.u32(), r.u32(), r.u32(), r.u8(), r.i64()) for _ in range(r.u32())]
    d["receipt"] = dict(orderId=r.u64(), code=r.str(), store=r.str(), total=r.u32(), count=r.u32(), unpriced=r.u32(),
                        status=r.str(), payment=r.str(), paid=r.i64())
    return d


class Phone:
    def __init__(self, ws): self.ws, self.n = ws, 0
    async def rpc(self, name, args=b""):
        self.n += 1
        await self.ws.send(call_procedure(self.n, name, args))
        while True:
            m = await self.ws.recv()
            r = R(m[1:])                      # m[0] = compression byte (0 = none)
            if r.u8() != 7: continue          # ServerMessage::ProcedureResult
            if r.u8() != 0: raise RuntimeError(r.str())
            return cart_state(r.bytes())


def store_point(k):
    return CENTER[0] + (k // 100 - 50) * 0.006, CENTER[1] + (k % 100 - 50) * 0.006


def pct(v, p):
    v = sorted(v); return round(v[min(len(v) - 1, int(len(v) * p))])


async def run(n, stores, items):
    async with httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=64)) as cl:
        toks, wsts = [], []
        for i in range(0, n, 100):
            rs = await asyncio.gather(*[cl.post(HOST + "/v1/identity") for _ in range(min(100, n - i))]); toks += [x.json()["token"] for x in rs]
        for i in range(0, n, 100):
            rs = await asyncio.gather(*[cl.post(HOST + "/v1/identity/websocket-token", headers={"Authorization": "Bearer " + t}) for t in toks[i:i + 100]])
            wsts += [x.json()["token"] for x in rs]
    lat, errors, charged = [], [], 0
    gate, opening = asyncio.Event(), asyncio.Semaphore(100)

    async def shopper(i, wst):
        nonlocal charged
        async with opening:
            ws = await websockets.connect(f"{HOST.replace('https', 'wss')}/v1/database/{DB}/subscribe?token={wst}&compression=None",
                                          subprotocols=["v2.bsatn.spacetimedb"], max_size=None, open_timeout=60)
        p = Phone(ws)
        async def t(name, args=b""):
            t0 = time.perf_counter(); st = await p.rpc(name, args); lat.append((time.perf_counter() - t0) * 1000); return st
        try:
            await gate.wait()
            k = random.randrange(stores); la, ln = store_point(k)
            await t("shop_set_payment", s("Load Visa"))
            st = await t("shop_locate", struct.pack("<ddd", la + random.uniform(-0.0003, 0.0003), ln, 12.0))
            if st["storeId"] != f"lt-{k}": errors.append(("wrong store", k, st["storeId"]))
            for j in range(items): st = await t("shop_bag_line", s(f"+{1001 + random.randrange(16)}@L{i}T{j}"))
            expect = st["total"]
            await t("shop_locate", struct.pack("<ddd", la + 300 / 111320, ln, 8.0))
            st = await t("shop_locate", struct.pack("<ddd", la + 330 / 111320, ln, 8.0))
            if st["storeId"] or st["receipt"]["total"] != expect or st["receipt"]["status"] != "paid": errors.append(("charge", expect, st["receipt"]))
            else: charged += 1
        finally:
            await ws.close()

    tasks = [asyncio.create_task(shopper(i, w)) for i, w in enumerate(wsts)]
    await asyncio.sleep(3 + n / 40); t0 = time.perf_counter(); gate.set()
    res = await asyncio.gather(*tasks, return_exceptions=True); wall = time.perf_counter() - t0
    fails = [str(x)[:80] for x in res if isinstance(x, Exception)]
    return {"shoppers": n, "walked_out_and_charged": charged, "calls": len(lat), "wall_s": round(wall, 1),
            "calls_per_s": round(len(lat) / wall), "p50_ms": pct(lat, .5), "p95_ms": pct(lat, .95), "p99_ms": pct(lat, .99),
            "errors": len(errors), "connection_failures": len(fails), "sample": (errors + fails)[:3]}


def admin_call(token, reducer, args):
    r = requests.post(f"{HOST}/v1/database/{DB}/call/{reducer}", headers={"Authorization": "Bearer " + token}, json=args, timeout=120)
    r.raise_for_status()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shoppers", type=int, default=300)
    ap.add_argument("--stores", type=int, default=2000)
    ap.add_argument("--items", type=int, default=6)
    ap.add_argument("--seed", type=int, help="create N synthetic stores (admin)")
    ap.add_argument("--clear", action="store_true", help="remove synthetic stores (admin)")
    ap.add_argument("--admin-token")
    a = ap.parse_args()
    if a.seed:
        for start in range(0, a.seed, 500): admin_call(a.admin_token, "seed_load_test", [start, min(500, a.seed - start), *CENTER])
        print("seeded", a.seed)
    elif a.clear:
        for _ in range(10): admin_call(a.admin_token, "clear_load_test", [500])
        print("cleared")
    else:
        print(json.dumps(asyncio.run(run(a.shoppers, a.stores, a.items)), indent=1))
