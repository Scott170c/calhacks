# SmartBag vision: Jetson Nano + 2 cameras + YOLOv8 (ROS 2)

The bag sees what goes in and what comes out, then tells the phone the same way the ESP32/RFID bag
does: `+1001@J3A2F0007` (add), `-1001` (remove). The phone app, the SpacetimeDB backend and the
walk-out payment are unchanged.

## YOLOv8, not a VLA

**Use YOLOv8 (nano).** A VLA (vision-language-action model, e.g. OpenVLA, RT-2) turns camera
images plus an instruction into robot *actions*; it is the wrong tool for "what item just went
into the bag", and it does not fit a Jetson Nano: OpenVLA is about 7 billion parameters (around
14 GB at fp16, 4 GB or more even 4-bit quantized) against the Nano's 4 GB shared CPU/GPU memory, and
it would run at well under one decision per second if at all. YOLOv8n is about 3 million
parameters, runs as a TensorRT FP16 engine, and leaves room to run it on two cameras several times a
second each. Items have to be recognised while a hand moves them through the rim, so frame rate
matters more than open-ended reasoning.

If you later want open-vocabulary recognition (new products without retraining), the step up is a
small detector like YOLO-World on a Jetson Orin, still not a VLA.

## How it works

```
 cam0 ─┐                     ┌─ tracker + rim crossing (cam0) ─┐
       ├─ vision_node: YOLOv8 ┤                                 ├─ /smartbag/camera_event
 cam1 ─┘   (one TensorRT      └─ tracker + rim crossing (cam1) ─┘            │
            engine, both                                                     ▼
            cameras)                                          fusion_node: one item = one line
                                                              (both cameras agree, or one camera
                                                               confidently), class -> SKU, local count
                                                                             │ /smartbag/bag_line
                                                                             ▼
                                         ble_bridge_node: USB serial -> ESP32 (BLE, as today) -> phone
                                                          or the Jetson's own Bluetooth (BlueZ)
                                         phone answers (OK / ERR / PAID) -> /smartbag/phone_ack
```

**Mounting.** Clip the two cameras to opposite sides of the bag rim, angled down and across the
opening, so each sees the mouth of the bag and part of the interior. Two views mean a hand that hides
an item from one camera rarely hides it from both.

**Inside zone.** In each camera image, the bag interior is a polygon (`inside_zone`, normalised
coordinates); its top edge is the rim. `scripts/snapshot_zones.py` draws it on a live frame so you
can line it up.

**Counting rules, per camera** (`core/crossing.py`):
- *Add*: an item tracked from outside the zone into it, staying on the inside for 2 frames.
- *Add (drop)*: an item first seen just inside the rim that then moves deeper: dropped too fast for any frame to catch it above the rim.
- *Remove*: an item tracked from inside the zone to outside.
- An item brought in and pulled straight back cancels itself. Items already lying in the bag never count.

**Fusion** (`core/fusion.py`): the same crossing seen by both cameras within 1.2 s is one item (label
chosen by confidence); a crossing seen by one camera counts if its confidence is at least 0.55. The
bag never asks to remove an item it never added, and each add carries a unique tag so a resent line is
ignored by the server. After `PAID` from the phone, the local count resets.

**Classes to SKUs.** `sku_map` in `config/smartbag.yaml`. The stock COCO model knows a few grocery
items (banana, apple, orange, broccoli, carrot, bottle, sandwich...), mapped to demo SKUs. For real
products, fine-tune YOLOv8n on photos of your catalog (one class per product, ~100-300 labelled images
per class taken from the bag cameras) and map each class to its SKU.

## Connecting to the phone

- **`transport: serial` (default)**: plug the existing SmartBag ESP32 into the Jetson by USB. Its
  current firmware already advertises the bag over BLE and forwards every line it reads on Serial, so
  nothing changes on the ESP32 or the phone. Lines are queued while the phone is disconnected.
- **`transport: bluez`**: the Jetson advertises the bag itself. The Nano dev kit has no Bluetooth;
  add an M.2 Wi-Fi/BT card (e.g. Intel 8265) or a USB dongle. Untested so far (no adapter here).
- **`transport: stdout`**: print lines, for bench testing.

## Setup on the Jetson

1. Check what you have: `cat /etc/nv_tegra_release` (JetPack), `ros2 --version`, `python3 --version`.
   Ultralytics needs Python 3.8+. On an original Nano (JetPack 4.6, Python 3.6) run inside the
   Ultralytics JetPack 4 container with ROS 2 there; on Orin Nano (JetPack 5/6) install natively.
2. Copy this folder into your ROS 2 workspace and run `scripts/install_jetson.sh`.
3. `scripts/export_engine.sh yolov8n.pt 416`: builds the TensorRT FP16 engine on the device.
4. Set the camera sources (`csi:0`/`csi:1` for ribbon cameras, `usb:0`/`usb:1` for USB) and run
   `python3 scripts/snapshot_zones.py` to line up each `inside_zone`.
5. `ros2 launch smartbag_vision smartbag.launch.py` (or `transport:=stdout` to watch lines without a phone).
6. Optional: `systemd/smartbag.service` starts it at boot.

Useful topics: `/smartbag/camera_event`, `/smartbag/bag_line`, `/smartbag/inventory`,
`/smartbag/fusion_log` (why something was or wasn't sent), `/smartbag/vision_status` (fps, inference
time, camera health), `/smartbag/<cam>/debug/compressed` (annotated frames; view with rqt_image_view).

Performance to expect: not yet measured on a Nano. YOLOv8n at 416 px as a TensorRT FP16 engine is
commonly reported around 20-40 ms per frame on an original Nano, i.e. roughly 10-20 fps per camera
with two cameras; tune `imgsz` (320 is faster) and `rate_hz`. Two USB cameras on the Nano's single USB
3 hub need MJPEG (set automatically) or lower resolutions; CSI cameras avoid this.

## Tests

`python3 -m pytest src/smartbag_vision/test` runs the counting, fusion, protocol and serial-link
tests with no ROS, camera or GPU. `test_data/` has scripted detections (`mock.yaml`) and two
synthetic camera videos (`video.yaml`) for running the whole ROS 2 pipeline on a laptop.
