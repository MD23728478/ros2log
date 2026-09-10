import json
import math
import re

from flask import current_app, jsonify, request
import yaml

from backend.api import blueprint
from runner.client import Ros2CommandError, ros2_command


TOPIC_NAME = re.compile(r"/[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*")
MESSAGE_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*/msg/[A-Za-z_][A-Za-z0-9_]*")


def _json_values(value):
    """Keep ROS values representable in JSON, including bytes and NaN."""
    if isinstance(value, dict):
        return {key: _json_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_values(item) for item in value]
    if isinstance(value, bytes):
        return list(value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


@blueprint.get("/topic-monitor")
def topic_monitor():
    """Read one message from the ROS topic selected by the caller."""
    topic = request.args.get("topic", "")
    if not TOPIC_NAME.fullmatch(topic) or len(topic) > 256:
        return jsonify(
            error="Provide a fully qualified topic name in the 'topic' query parameter."
        ), 400

    try:
        # Discover the type instead of assuming the topic contains a temperature.
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

        # --once ends the subscription after one message. The runner also
        # enforces its command timeout if discovery or subscription gets stuck.
        wait_seconds = min(5.0, current_app.config["ROS2_COMMAND_TIMEOUT"] / 2)
        result = ros2_command(
            "topic", "echo", topic, message_type,
            "--once", "--timeout", str(wait_seconds),
            "--full-length", "--no-lost-messages",
            "--qos-reliability", "best_effort",
        )
    except Ros2CommandError as error:
        return jsonify(error=str(error)), 503
    except json.JSONDecodeError:
        return jsonify(error="ROS 2 runner returned invalid JSON."), 502

    if result["return_code"] != 0:
        return jsonify(error="Could not read a message from the topic."), 502
    if not result["stdout"].strip():
        return jsonify(error="No message was received before the timeout."), 504

    try:
        # ROS echo prints YAML followed by '---', an empty next document.
        messages = [
            message for message in yaml.safe_load_all(result["stdout"])
            if message is not None
        ]
        if len(messages) != 1 or not isinstance(messages[0], dict):
            raise ValueError("Expected one ROS message")
        message = _json_values(messages[0])
        json.dumps(message, allow_nan=False)
    except (yaml.YAMLError, TypeError, ValueError, RecursionError):
        return jsonify(error="ROS 2 returned an invalid message."), 502

    response = jsonify(
        source="ros2",
        topic=topic,
        message_type=message_type,
        latest_message=message,
    )
    response.headers["Cache-Control"] = "no-store"
    return response
