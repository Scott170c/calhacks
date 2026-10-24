"""How bag lines reach the phone.

  serial  (default) USB to the existing SmartBag ESP32, which already advertises the bag over BLE
          (Nordic UART) and forwards every line it reads on Serial. No firmware change needed on the
          ESP32. Its Serial output tells us when the phone connects and what the phone answers.
  bluez   The Jetson itself is the BLE peripheral (needs a Bluetooth adapter: the Nano dev kit has
          none built in; use an M.2 Wi-Fi/BT card or a USB dongle). BlueZ GATT server over D-Bus.
  stdout  Print lines (bench testing).

All transports queue lines while the phone is not connected and send them, in order, once it is.
"""
import collections
import threading
import time


class Transport(object):
    def __init__(self, on_ack=None, on_status=None):
        self.on_ack = on_ack or (lambda text: None)
        self.on_status = on_status or (lambda status: None)
        self.queue = collections.deque(maxlen=200)
        self.phone_connected = False
        self.lock = threading.Lock()

    def send(self, line):
        with self.lock:
            self.queue.append(line)
        self.pump()

    def pump(self):
        pass

    def close(self):
        pass


class StdoutTransport(Transport):
    def __init__(self, **kw):
        super(StdoutTransport, self).__init__(**kw)
        self.phone_connected = True
        self.sent = []

    def pump(self):
        with self.lock:
            while self.queue:
                line = self.queue.popleft()
                self.sent.append(line)
                print("BAG -> PHONE: " + line, flush=True)


class SerialEsp32Transport(Transport):
    """Talks to the ESP32 SmartBag firmware over USB serial (115200 8N1)."""

    def __init__(self, port="/dev/ttyUSB0", baud=115200, serial_factory=None, **kw):
        super(SerialEsp32Transport, self).__init__(**kw)
        self.port, self.baud = port, baud
        self.serial_factory = serial_factory
        self.ser = None
        self.stop_evt = threading.Event()
        self.reader = threading.Thread(target=self._run, name="esp32-serial", daemon=True)
        self.reader.start()

    def _open(self):
        if self.serial_factory:
            return self.serial_factory()
        import serial  # pyserial
        s = serial.Serial(self.port, self.baud, timeout=0.2)
        time.sleep(2.0)  # opening the port resets most ESP32 boards; give it time to boot
        return s

    def _run(self):
        buf = b""
        while not self.stop_evt.is_set():
            if self.ser is None:
                try:
                    self.ser = self._open()
                    self.on_status("serial open %s" % self.port)
                except Exception as e:  # noqa: BLE001
                    self.on_status("serial unavailable: %s" % e)
                    time.sleep(2.0)
                    continue
            try:
                chunk = self.ser.read(256)
            except Exception as e:  # noqa: BLE001
                self.on_status("serial lost: %s" % e)
                self.ser, self.phone_connected = None, False
                continue
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self._handle(raw.decode("utf-8", "replace").strip())

    def _handle(self, text):
        if not text:
            return
        if text == "phone connected":
            self.phone_connected = True
            self.on_status("phone connected")
            self.pump()
        elif text == "phone disconnected":
            self.phone_connected = False
            self.on_status("phone disconnected")
        elif text.startswith("phone: "):
            self.on_ack(text[len("phone: "):])
        elif text.startswith("not connected, dropped: "):
            # the ESP32 lost the phone between our check and its send: requeue at the front
            with self.lock:
                self.queue.appendleft(text[len("not connected, dropped: "):])
            self.phone_connected = False
        elif text.endswith("advertising"):
            self.on_status(text)

    def pump(self):
        if self.ser is None or not self.phone_connected:
            return
        with self.lock:
            while self.queue:
                line = self.queue.popleft()
                try:
                    self.ser.write((line + "\n").encode("utf-8"))
                    self.ser.flush()
                except Exception as e:  # noqa: BLE001
                    self.queue.appendleft(line)
                    self.on_status("serial write failed: %s" % e)
                    break
                time.sleep(0.02)   # let the ESP32 notify each line separately

    def close(self):
        self.stop_evt.set()
        try:
            self.ser and self.ser.close()
        except Exception:  # noqa: BLE001
            pass


NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # phone -> bag (write)
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # bag -> phone (notify)


class BluezNusTransport(Transport):
    """The Jetson as a BLE peripheral advertising the SmartBag Nordic UART Service via BlueZ (D-Bus).

    Requires: a Bluetooth adapter, bluetoothd running (with --experimental on older BlueZ for LE
    advertising), python3-dbus and python3-gi. Runs a GLib main loop in a background thread.
    """

    def __init__(self, device_name="SmartBag-01", adapter=None, **kw):
        super(BluezNusTransport, self).__init__(**kw)
        self.device_name = device_name
        self.adapter_path = adapter
        self.tx = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="bluez", daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self._serve()
        except Exception as e:  # noqa: BLE001
            self.on_status("bluez unavailable: %s" % e)

    def _serve(self):
        import dbus
        import dbus.exceptions
        import dbus.mainloop.glib
        import dbus.service
        from gi.repository import GLib

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()
        BLUEZ, GATT_MGR, ADV_MGR = "org.bluez", "org.bluez.GattManager1", "org.bluez.LEAdvertisingManager1"
        OM, PROPS = "org.freedesktop.DBus.ObjectManager", "org.freedesktop.DBus.Properties"
        GATT_SVC, GATT_CHR = "org.bluez.GattService1", "org.bluez.GattCharacteristic1"
        transport = self

        om = dbus.Interface(bus.get_object(BLUEZ, "/"), OM)
        adapter = self.adapter_path
        if not adapter:
            for path, ifaces in om.GetManagedObjects().items():
                if GATT_MGR in ifaces and ADV_MGR in ifaces:
                    adapter = path
                    break
        if not adapter:
            raise RuntimeError("no Bluetooth LE adapter with GATT server + advertising support")
        dbus.Interface(bus.get_object(BLUEZ, adapter), PROPS).Set("org.bluez.Adapter1", "Powered", dbus.Boolean(1))

        class Application(dbus.service.Object):
            def __init__(self):
                self.path = "/space/mana/smartbag"
                self.services = []
                dbus.service.Object.__init__(self, bus, self.path)

            @dbus.service.method(OM, out_signature="a{oa{sa{sv}}}")
            def GetManagedObjects(self):
                res = {}
                for s in self.services:
                    res[s.path] = s.props()
                    for c in s.chars:
                        res[c.path] = c.props()
                return res

        class Service(dbus.service.Object):
            def __init__(self, app):
                self.path = app.path + "/service0"
                self.chars = []
                dbus.service.Object.__init__(self, bus, self.path)

            def props(self):
                return {GATT_SVC: {"UUID": NUS_SERVICE, "Primary": True,
                                   "Characteristics": dbus.Array([c.path for c in self.chars], signature="o")}}

        class Characteristic(dbus.service.Object):
            def __init__(self, svc, index, uuid, flags):
                self.path = svc.path + "/char%d" % index
                self.svc, self.uuid, self.flags = svc, uuid, flags
                self.notifying = False
                dbus.service.Object.__init__(self, bus, self.path)

            def props(self):
                return {GATT_CHR: {"Service": self.svc.path, "UUID": self.uuid, "Flags": self.flags}}

            @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface):
                return self.props()[GATT_CHR]

            @dbus.service.method(GATT_CHR, in_signature="aya{sv}")
            def WriteValue(self, value, options):
                text = bytes(bytearray(value)).decode("utf-8", "replace").strip()
                if text:
                    transport.on_ack(text)

            @dbus.service.method(GATT_CHR)
            def StartNotify(self):
                self.notifying = True
                transport.phone_connected = True
                transport.on_status("phone connected")
                GLib.idle_add(transport._flush_glib)

            @dbus.service.method(GATT_CHR)
            def StopNotify(self):
                self.notifying = False
                transport.phone_connected = False
                transport.on_status("phone disconnected")

            @dbus.service.signal(PROPS, signature="sa{sv}as")
            def PropertiesChanged(self, interface, changed, invalidated):
                pass

            def notify(self, data):
                if self.notifying:
                    self.PropertiesChanged(GATT_CHR, {"Value": dbus.Array([dbus.Byte(b) for b in data], signature="y")}, [])

        class Advertisement(dbus.service.Object):
            def __init__(self):
                self.path = "/space/mana/smartbag/adv0"
                dbus.service.Object.__init__(self, bus, self.path)

            @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface):
                return {"Type": "peripheral", "ServiceUUIDs": dbus.Array([NUS_SERVICE], signature="s"),
                        "LocalName": dbus.String(transport.device_name), "Includes": dbus.Array(["tx-power"], signature="s")}

            @dbus.service.method("org.bluez.LEAdvertisement1")
            def Release(self):
                pass

        app = Application()
        svc = Service(app)
        rx = Characteristic(svc, 0, NUS_RX, ["write", "write-without-response"])
        tx = Characteristic(svc, 1, NUS_TX, ["notify"])
        svc.chars = [rx, tx]
        app.services = [svc]
        self.tx = tx
        self._glib = GLib
        dbus.Interface(bus.get_object(BLUEZ, adapter), GATT_MGR).RegisterApplication(
            app.path, {}, reply_handler=lambda: self.on_status("GATT ready"), error_handler=lambda e: self.on_status("GATT error: %s" % e))
        dbus.Interface(bus.get_object(BLUEZ, adapter), ADV_MGR).RegisterAdvertisement(
            Advertisement().path, {}, reply_handler=lambda: self.on_status("%s advertising" % self.device_name),
            error_handler=lambda e: self.on_status("advertising error: %s" % e))
        self.ready.set()
        GLib.MainLoop().run()

    def _flush_glib(self):
        with self.lock:
            while self.queue and self.phone_connected and self.tx is not None:
                data = (self.queue.popleft() + "\n").encode("utf-8")
                for i in range(0, len(data), 20):     # default ATT payload; the apps reassemble until "\n"
                    self.tx.notify(data[i:i + 20])
        return False

    def pump(self):
        if self.ready.is_set() and self.phone_connected:
            self._glib.idle_add(self._flush_glib)


def make_transport(kind, on_ack=None, on_status=None, port="/dev/ttyUSB0", baud=115200, device_name="SmartBag-01"):
    if kind == "serial":
        return SerialEsp32Transport(port=port, baud=baud, on_ack=on_ack, on_status=on_status)
    if kind == "bluez":
        return BluezNusTransport(device_name=device_name, on_ack=on_ack, on_status=on_status)
    if kind == "stdout":
        return StdoutTransport(on_ack=on_ack, on_status=on_status)
    raise ValueError("unknown transport %r (serial, bluez, stdout)" % kind)
