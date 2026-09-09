import random

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, Float64, String


class TestTopics(Node):
    def __init__(self) -> None:
        super().__init__("ros2log_test_topics")
        self.temperature = self.create_publisher(
            Float64, "/ros2log/test/temperature", 10
        )
        self.battery = self.create_publisher(
            Float32, "/ros2log/test/battery", 10
        )
        self.status = self.create_publisher(String, "/ros2log/test/status", 10)
        self.create_timer(0.5, self.publish_values)

    def publish_values(self) -> None:
        temperature = Float64()
        temperature.data = random.uniform(15.0, 35.0)
        self.temperature.publish(temperature)

        battery = Float32()
        battery.data = random.uniform(0.0, 100.0)
        self.battery.publish(battery)

        status = String()
        status.data = random.choice(["idle", "moving", "charging"])
        self.status.publish(status)


def main() -> None:
    rclpy.init()
    node = TestTopics()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
