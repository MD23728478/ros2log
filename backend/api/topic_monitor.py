import math
import re

from flask import current_app, jsonify, request

from backend.api import blueprint
from runner.client import Ros2CommandError, ros2_command


TOPIC_NAME = re.compile(r"/[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*")
MESSAGE_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*/msg/[A-Za-z_][A-Za-z0-9_]*")
HZ_OUTPUT = re.compile(r"^average rate:[ \t]*(\S+)[ \t]*\r?\n", re.MULTILINE)
BANDWIDTH_OUTPUT = re.compile(
    r"^[ \t]*(\S+)[ \t]+([A-Za-z]+)/s[ \t]+from[ \t]+\d+[ \t]+messages[ \t]*\r?\n",
    re.MULTILINE,
)
BANDWIDTH_UNITS = {"B": 1, "KB": 1000, "MB": 1000000}


def _measurement(output, pattern, *, bandwidth=False):
    """Use the latest complete measurement line, ignoring startup messages."""
    matches = list(pattern.finditer(output))
    if not matches:
        return None
    match = matches[-1]
    value = float(match[1])
    if bandwidth:
        if match[2] not in BANDWIDTH_UNITS:
            raise ValueError("Unsupported bandwidth unit")
        value *= BANDWIDTH_UNITS[match[2]]
    if not math.isfinite(value) or value < 0:
        raise ValueError("Invalid measurement")
    return value


@blueprint.get("/topic-monitor")
def topic_monitor():
    """Measure the receiving frequency and bandwidth of a selected ROS topic."""
    topic = request.args.get("topic", "")
    if not TOPIC_NAME.fullmatch(topic) or len(topic) > 256:
        return jsonify(
            error="Provide a fully qualified topic name in the 'topic' query parameter."
        ), 400

    try:
        # Check discovery before starting measurements on a possibly absent topic.
        type_result = ros2_command("topic", "--include-hidden-topics", "type", topic)
        if type_result["return_code"] != 0:
            # Jazzy's `topic type` exits with code 1 and no output when the
            # selected topic is absent. Other failures remain upstream errors.
            if (
                type_result["return_code"] == 1
                and not type_result["stdout"].strip()
                and not type_result["stderr"].strip()
            ):
                return jsonify(error="Topic was not found in the ROS graph."), 404
            return jsonify(error="Could not determine the topic's message type."), 502

        message_types = type_result["stdout"].split()
        if not message_types:
            return jsonify(error="Topic was not found in the ROS graph."), 404
        if len(message_types) != 1:
            return jsonify(error="Topic has multiple message types."), 409
        message_type = message_types[0]
        if not MESSAGE_TYPE.fullmatch(message_type):
            return jsonify(error="ROS 2 returned an invalid message type."), 502

        # hz and bw run continuously. Sample each for at most five seconds,
        # preserving its printed statistics when the runner ends the command.
        sample_seconds = min(5.0, current_app.config["ROS2_COMMAND_TIMEOUT"])
        readings = {}
        for verb, pattern in (("hz", HZ_OUTPUT), ("bw", BANDWIDTH_OUTPUT)):
            arguments = ["topic", verb, topic, "--window", "100"]
            if verb == "hz":
                arguments.append("--wall-time")
            result = ros2_command(
                *arguments,
                timeout_seconds=sample_seconds,
                capture_on_timeout=True,
            )
            sampling_finished = (
                result["return_code"] == 124 and result.get("timed_out") is True
            )
            if result["return_code"] != 0 and not sampling_finished:
                return jsonify(error=f"ROS 2 could not measure topic {verb}."), 502
            try:
                value = _measurement(result["stdout"], pattern, bandwidth=verb == "bw")
            except ValueError:
                return jsonify(error=f"ROS 2 returned an invalid {verb} measurement."), 502
            if value is None:
                return jsonify(
                    error=f"Not enough ROS traffic to measure topic {verb} within the sampling period."
                ), 504
            readings[verb] = value
    except Ros2CommandError as error:
        return jsonify(error=str(error)), 503

    response = jsonify(
        source="ros2",
        topic=topic,
        frequency_hz=readings["hz"],
        bandwidth_bytes_per_second=readings["bw"],
    )
    response.headers["Cache-Control"] = "no-store"
    return response
