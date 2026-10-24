# SmartBag: just walk out

Cal Hacks 13.0 · built on **SpacetimeDB**

Drop groceries into a SmartBag and walk out of the store. The bag tells your phone what's inside over Bluetooth, your phone reports where you are, and a SpacetimeDB module does everything else: it works out which store you're in, prices the bag with that store's catalog, and **charges you the moment you leave**. No scanning, no checkout line, no Pay button.

```
 ┌──────────────┐  BLE (Nordic UART)  ┌──────────────────┐  one WebSocket   ┌──────────────────────────────┐
 │ SmartBag     │ ──── "+1005" ─────▶ │ Phone app        │ ───────────────▶ │ SpacetimeDB module           │
 │ ESP32 + RFID │ ◀── "OK +1005 4.69" │ Android · iOS    │  procedures:     │ smartcart-5dt35 (Maincloud)  │
 └──────────────┘ ◀── "PAID 7KQ2XD" ─ │ GPS fixes + bag  │  shop_locate,    │ · geofence (grid index)      │
                                      │ lines, no Pay    │  shop_bag_line…  │ · bag parsing + tag dedupe   │
                                      └──────────────────┘ ◀── priced bag ─ │ · per-store pricing          │
                                                                            │ · walk-out = payment         │
                         ┌──────────────────────────────┐  live subscription│ · multi-tenant store staff   │
                         │ Store console (web)          │ ◀──────────────── │ · scheduled cleanup          │
                         │ shoppers, bags, orders, feed │ ───── reducers ──▶│                              │
                         └──────────────────────────────┘                   └──────────────────────────────┘
```

## Branches

Each component lives on its own branch so it can be developed, reviewed and demoed independently.

| Branch | Component | Folder |
|---|---|---|
| `spacetimedb-module` | The backend: tables, reducers, procedures, views, walk-out payment, cleanup schedule | `server/` |
| `android-app` | Native Android customer app (Kotlin + Compose), hand-written SpacetimeDB binary protocol client | `android/`, `tools/` |
| `ios-app` | Native iPhone customer app (SwiftUI) | `ios/` |
| `store-console` | Live store dashboard: shoppers, bags, orders, catalog editing (SpacetimeDB TypeScript SDK, subscriptions) | `console/` |
| `bag-firmware` | ESP32 firmware that advertises the bag and streams item reads over BLE | `firmware/` |
| `jetson-vision` | Jetson Nano + 2 cameras: YOLOv8 sees items go in and out of the bag (ROS 2) | `jetson/` |
| `load-tests` | Scale benchmarks: thousands of stores, hundreds of concurrent walk-outs | `load-tests/` |
| `project-overview` | This README and the architecture notes | `README.md`, `docs/` |
| `website` | Public site for bagitwith.us: how it works, setup, help, store operator info | `website/` |

Architecture notes and scale measurements: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Each branch below is opened as its own pull request into `main`.

## How a trip works

1. **Walk in.** The phone sends a GPS fix. The module looks only at stores in the 3×3 grid cells around the fix and places the shopper in the one they're standing in.
2. **Shop.** Every item the bag reads (`+1005@E28011`) is forwarded verbatim; the module parses it, ignores repeat reads of the same RFID tag, and returns the bag priced for *this* store.
3. **Walk out.** Two accurate fixes clearly outside the store (radius + 40 m) and the module, in one transaction, prices the bag, records the order, charges the saved card (simulated) and empties the bag. The phone shows the receipt and the bag blinks `PAID`.

## Why SpacetimeDB

The whole backend is one module: geofencing, pricing, payment and permissions run inside the database next to the data, so every decision is a single transaction with no app server in between. The store console is a live subscription, so a shopper's bag appears on the store's screen as items drop in.

Measured on Maincloud: 300 phones completing full walk-out trips among 2,000 stores at the same time, about 580 calls/s, median 367 ms round trip from California, zero errors, every bag charged exactly once. Module work per call is 0.4 to 2 ms. Details in `docs/ARCHITECTURE.md` and the `load-tests` branch.

## Demo

Database `smartcart-5dt35` on SpacetimeDB Maincloud. Two demo stores are seeded in San Francisco; operators can pin a new store at their current location from the console. In the phone apps, long-press the bag status to drop in a random item, and long-press the store name to simulate walking out.
