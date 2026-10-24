# SmartBag load tests

All numbers measured on SpacetimeDB Maincloud (database `smartcart-5dt35`) from a single client machine in California, October 2026.

| Test | Result |
|---|---|
| 300 phones, full walk-out trips (10 calls each), 2,000 stores | 3,000 calls in 5.1 s · ~580 calls/s · p50 367 ms · p95 1.1 s · **0 errors** · every shopper placed in the right store · every bag charged exactly once |
| 800 phones, same trip | the 700 that connected all charged correctly; 100 WebSocket handshakes timed out on the single test machine |
| Reducers over WebSocket (`ws_reducer_bench.mjs`, 200 connections) | 2,813 calls/s · p50 65 ms (network round trip) |
| HTTP `/call` (any reducer or procedure, even read-only) | capped near 70 calls/s per database, so the phone apps use WebSockets |
| Seeding 2,000 stores + 32,000 products | about 1.3 s |
| Module execution per call | 0.4 to 2 ms |

- `walkout_load.py`: simulated phones over SpacetimeDB's binary WebSocket protocol (same wire code as the apps). Seed, run, clear: see the docstring.
- `ws_reducer_bench.mjs`: reducer throughput with the official TypeScript SDK (needs the console bundle: `console/build.sh` on the `store-console` branch).
