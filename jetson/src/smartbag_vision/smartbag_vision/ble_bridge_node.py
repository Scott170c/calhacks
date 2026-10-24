"""ble_bridge_node: /smartbag/bag_line -> phone (via the ESP32 over serial, or BlueZ), phone answers -> /smartbag/phone_ack."""
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .core.transport import make_transport


class BleBridgeNode(Node):
    def __init__(self):
        super().__init__("ble_bridge_node")
        p = self.declare_parameter
        kind = p("transport", "serial").value
        self.pub_ack = self.create_publisher(String, "/smartbag/phone_ack", 20)
        self.pub_status = self.create_publisher(String, "/smartbag/link_status", 10)
        self.link = make_transport(kind, on_ack=self._ack, on_status=self._status,
                                   port=p("serial_port", "/dev/ttyUSB0").value, baud=p("baud", 115200).value,
                                   device_name=p("device_name", "SmartBag-01").value)
        self.create_subscription(String, "/smartbag/bag_line", lambda m: self.link.send(m.data), 50)
        self.create_timer(1.0, self.link.pump)
        self.get_logger().info("bridge using %s transport" % kind)

    def _ack(self, text):
        self.get_logger().info("phone: %s" % text)
        self.pub_ack.publish(String(data=text))

    def _status(self, text):
        self.get_logger().info("link: %s" % text)
        self.pub_status.publish(String(data=text))

    def destroy_node(self):
        self.link.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = BleBridgeNode()
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
