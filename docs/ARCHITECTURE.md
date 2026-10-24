# Architecture notes

```text
SmartBag architecture notes (updated 2026-10-23 late, v3.0: walk-out payment, built to scale)


Product rule: shoppers never press Pay. The bag is charged automatically when the phone leaves the store. The phone is deliberately not a subscription client; it does request/response calls only.

SpacetimeDB
- Module /workspace/smartbag/smartbag-db/spacetimedb/src/index.ts (TypeScript, SpacetimeDB 2.13). Publish: cd /workspace/smartbag/smartbag-db && spacetime publish smartcart-5dt35 --server maincloud --yes. Schema changes need --delete-data=always; init then re-seeds Bayside Grocer + Mission Fresh and makes a NEW operator_code, which must be copied into app/spacetime/operatorCode.
- Scale design: store.cell = 0.01 degree grid key (btree), so a GPS fix examines only the 3x3 nearby cells (radius capped at 400 m). shopper, cart_item and bag_event are indexed by store_id; shop_order and order_line by (store_id, UTC day). A scheduled cleanup every 5 min drops bag events older than 1 h and idle empty shoppers older than 12 h. Multi-tenant: store_staff + store_invite (private), join_store(code), rotate_invite, pin_store (anyone, max 5, creator becomes staff), view my_stores; global admins in the operator table via claim_operator(code).
- Walk-out payment (doLocate/walkOut): membership is sticky. Leaving = a fix farther than radius + 40 m + accuracy, with accuracy <= 75 m, twice in a row (outsideFixes). The same transaction then prices the bag at that store, writes shop_order (trigger walkout, status paid | payment_due, payment label, unpricedCount) + order_line, logs WALKOUT to bag_event and empties the cart. There is no manual checkout.
- Phone API = procedures returning CartState (store, priced lines, payment, leaving, lastReceipt): shop_state, shop_locate(lat,lng,acc), shop_bag_line, shop_remove, shop_set_bag, shop_set_payment. The same operations exist as reducers for SDK clients. Admin helpers: seed_load_test(start,count,lat,lng) creates lt-N stores, clear_load_test(count), reset_demo(storeId, or '' for all).

Measured on Maincloud (2026-10-23): HTTP /call is capped at about 70 calls/s per database whatever the work (fixed per-request cost), so the phone does NOT use HTTP. Over one WebSocket per phone, 300 phones doing full walk-out trips (10 calls each) among 2,000 stores: 3,000 calls in 5.1 s (about 580 calls/s), p50 367 ms, p95 1.1 s, 0 errors, every store resolved correctly, every bag charged exactly once. With 800 phones, the 700 that connected all charged correctly; 100 socket handshakes timed out on the single test machine. Reducers over WebSocket (Node SDK benchmark) reached 2,800 calls/s, p50 65 ms. Module work per call is 0.4-2 ms. Load-test data was removed afterwards.


Store console (runs as a Mana app; source on the store-console branch). Official TS SDK bundle at spacetime/client/code (rebuild in /workspace/smartbag/console: spacetime generate --lang typescript --out-dir ./bindings --module-path ../smartbag-db/spacetimedb && npx esbuild entry.ts --bundle --format=esm --platform=browser --target=es2020 --minify --outfile=dist/stdb-client.mjs). It subscribes globally only to store + my_stores, plus ONE selected store's rows (header switcher, ?store=), swapping that subscription when the store changes. Tabs: Live, Orders (last 2 UTC days, paid or payment due), Store (settings + catalog), All stores (pin here), Customer app, Bag hardware. Reconnects with backoff.

Retired: v1 Firebase backend, the smartbag-api service, manual checkout (2.0).
Protocol: bag->phone lines "1005"|"+1005"|"-1005"|"+1005@UID"|JSON; phone->bag "OK +1005 4.69", "OK -1005", "ERR 9999 unknown", "PAID <code>" (sent after walk-out). NUS 6e400001-b5a3-f393-e0a9-e50e24dcca9e, RX ...0002, TX ...0003.
```