#!/usr/bin/env python3
"""Fast loopback simulator for batch experiments (Phase 7/8 trial runners) where Gazebo's
real time factor is a bottleneck. Integrates a unicycle model from /cmd_vel at 50 Hz,
publishes /odom and TF odom -> base_link, fakes /scan by ray casting against the static
map, and publishes an identity TF map -> odom (no AMCL needed: this node is the localizer).
"""

import math
import os

import rclpy
import yaml
from geometry_msgs.msg import Quaternion, TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster


def yaw_to_quaternion(yaw: float) -> Quaternion:
    q = Quaternion()
    q.z = math.sin(yaw / 2.0)
    q.w = math.cos(yaw / 2.0)
    return q


class OccupancyMap:
    def __init__(self, yaml_path: str):
        with open(yaml_path, "r") as f:
            meta = yaml.safe_load(f)
        pgm_path = os.path.join(os.path.dirname(yaml_path), meta["image"])
        self.resolution = float(meta["resolution"])
        self.origin_x, self.origin_y = float(meta["origin"][0]), float(meta["origin"][1])
        self.occupied_thresh = float(meta["occupied_thresh"])
        self.negate = int(meta.get("negate", 0))
        self.width, self.height, self.data = self._read_pgm(pgm_path)

    @staticmethod
    def _read_pgm(path: str):
        with open(path, "rb") as f:
            magic = f.readline().strip()
            if magic != b"P5":
                raise ValueError(f"unsupported PGM magic {magic!r} in {path}")
            dims = f.readline().split()
            width, height = int(dims[0]), int(dims[1])
            f.readline()  # maxval
            data = f.read(width * height)
        return width, height, data

    def is_occupied(self, x: float, y: float) -> bool:
        col = int((x - self.origin_x) / self.resolution)
        row_from_bottom = int((y - self.origin_y) / self.resolution)
        row = self.height - 1 - row_from_bottom
        if col < 0 or col >= self.width or row < 0 or row >= self.height:
            return True  # outside the mapped area counts as an obstacle
        pixel = self.data[row * self.width + col]
        prob = (255 - pixel) / 255.0 if self.negate == 0 else pixel / 255.0
        return prob > self.occupied_thresh


class LoopbackSimNode(Node):
    def __init__(self):
        super().__init__("loopback_sim_node")
        self.declare_parameter("map_yaml", "")
        self.declare_parameter("initial_x", 1.0)
        self.declare_parameter("initial_y", 6.0)
        self.declare_parameter("initial_theta", 0.0)
        self.declare_parameter("control_hz", 50.0)
        self.declare_parameter("scan_hz", 10.0)
        self.declare_parameter("scan_samples", 360)
        self.declare_parameter("scan_max_range", 10.0)
        self.declare_parameter("scan_step", 0.05)

        map_yaml = self.get_parameter("map_yaml").value
        if not map_yaml:
            raise RuntimeError("loopback_sim_node requires the map_yaml parameter")
        self.map = OccupancyMap(map_yaml)

        self.x = float(self.get_parameter("initial_x").value)
        self.y = float(self.get_parameter("initial_y").value)
        self.theta = float(self.get_parameter("initial_theta").value)
        self.v = 0.0
        self.w = 0.0

        self.odom_pub = self.create_publisher(Odometry, "odom", 10)
        self.scan_pub = self.create_publisher(LaserScan, "scan", 10)
        self.tf_broadcaster = TransformBroadcaster(self)
        self.static_tf_broadcaster = StaticTransformBroadcaster(self)
        self._publish_map_to_odom()

        self.create_subscription(Twist, "cmd_vel", self._cmd_vel_cb, 10)

        control_period = 1.0 / float(self.get_parameter("control_hz").value)
        scan_period = 1.0 / float(self.get_parameter("scan_hz").value)
        self._last_control_time = self.get_clock().now()
        self.create_timer(control_period, self._control_step)
        self.create_timer(scan_period, self._scan_step)

        self.get_logger().info(
            f"loopback_sim_node ready at ({self.x:.2f}, {self.y:.2f}, {self.theta:.2f})")

    def _publish_map_to_odom(self):
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = "map"
        t.child_frame_id = "odom"
        t.transform.rotation.w = 1.0
        self.static_tf_broadcaster.sendTransform(t)

    def _cmd_vel_cb(self, msg: Twist):
        self.v = msg.linear.x
        self.w = msg.angular.z

    def _control_step(self):
        now = self.get_clock().now()
        dt = (now - self._last_control_time).nanoseconds / 1e9
        self._last_control_time = now
        if dt <= 0.0:
            return

        self.theta += self.w * dt
        self.theta = math.atan2(math.sin(self.theta), math.cos(self.theta))
        self.x += self.v * math.cos(self.theta) * dt
        self.y += self.v * math.sin(self.theta) * dt

        odom = Odometry()
        odom.header.stamp = now.to_msg()
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_link"
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.orientation = yaw_to_quaternion(self.theta)
        odom.twist.twist.linear.x = self.v
        odom.twist.twist.angular.z = self.w
        self.odom_pub.publish(odom)

        t = TransformStamped()
        t.header.stamp = now.to_msg()
        t.header.frame_id = "odom"
        t.child_frame_id = "base_link"
        t.transform.translation.x = self.x
        t.transform.translation.y = self.y
        t.transform.rotation = yaw_to_quaternion(self.theta)
        self.tf_broadcaster.sendTransform(t)

    def _scan_step(self):
        samples = int(self.get_parameter("scan_samples").value)
        max_range = float(self.get_parameter("scan_max_range").value)
        step = float(self.get_parameter("scan_step").value)
        angle_min, angle_max = -math.pi, math.pi
        increment = (angle_max - angle_min) / samples

        ranges = []
        for i in range(samples):
            angle = self.theta + angle_min + i * increment
            ranges.append(self._cast_ray(angle, max_range, step))

        scan = LaserScan()
        scan.header.stamp = self.get_clock().now().to_msg()
        scan.header.frame_id = "base_link"
        scan.angle_min = angle_min
        scan.angle_max = angle_max
        scan.angle_increment = increment
        scan.time_increment = 0.0
        scan.scan_time = 1.0 / float(self.get_parameter("scan_hz").value)
        scan.range_min = 0.05
        scan.range_max = max_range
        scan.ranges = ranges
        self.scan_pub.publish(scan)

    def _cast_ray(self, angle: float, max_range: float, step: float) -> float:
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        t = 0.0
        while t < max_range:
            wx, wy = self.x + t * cos_a, self.y + t * sin_a
            if self.map.is_occupied(wx, wy):
                return t
            t += step
        return max_range


def main():
    rclpy.init()
    node = LoopbackSimNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
