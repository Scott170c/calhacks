"""fusion_node: /smartbag/camera_event from both cameras -> one bag line per real item -> /smartbag/bag_line."""
import json

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String

from .core.fusion import EventFuser
from .core.protocol import parse_ack


class FusionNode(Node):
    def __init__(self):
        super().__init__("fusion_node")
        p = self.declare_parameter
        sku_map = [x for x in p("sku_map", [""]).value if x]
        self.fuser = EventFuser(sku_map, window_s=p("window_s", 1.2).value, hold_s=p("hold_s", 0.6).value,
                                single_cam_min_conf=p("single_cam_min_conf", 0.55).value)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.pub_line = self.create_publisher(String, "/smartbag/bag_line", 50)
        self.pub_inv = self.create_publisher(String, "/smartbag/inventory", latched)
        self.pub_log = self.create_publisher(String, "/smartbag/fusion_log", 20)
        self.create_subscription(String, "/smartbag/camera_event", self._on_event, 50)
        self.create_subscription(String, "/smartbag/phone_ack", self._on_ack, 20)
        self.create_timer(0.1, self._tick)
        self.logged = 0
        self.get_logger().info("fusion ready: %d classes mapped to SKUs" % len(self.fuser.sku_map))
        self._publish_inventory()

    def _on_event(self, msg):
        try:
            ev = json.loads(msg.data)
        except ValueError:
            return
        self._send(self.fuser.push(ev))

    def _tick(self):
        self._send(self.fuser.flush())
        while self.logged < len(self.fuser.log):
            self.pub_log.publish(String(data=json.dumps(self.fuser.log[self.logged])))
            self.logged += 1
        if self.logged > 40:   # the fuser keeps only the last 50 entries
            self.logged = len(self.fuser.log)

    def _send(self, lines):
        for line in lines:
            self.pub_line.publish(String(data=line))
            self.get_logger().info("bag line %s" % line)
        if lines:
            self._publish_inventory()

    def _on_ack(self, msg):
        ack = parse_ack(msg.data)
        if ack["kind"] == "paid":
            self.get_logger().info("paid (%s): bag cleared" % ack["code"])
            self.fuser.reset()
            self.logged = len(self.fuser.log) - 1
            self._publish_inventory()
        elif ack["kind"] == "err":
            self.get_logger().warn("phone: %s" % ack["raw"])

    def _publish_inventory(self):
        self.pub_inv.publish(String(data=json.dumps(self.fuser.inventory)))


def main(args=None):
    rclpy.init(args=args)
    node = FusionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
