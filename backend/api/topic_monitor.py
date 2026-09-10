from flask import jsonify

from backend.api import blueprint


@blueprint.get("/topic-monitor")
def topic_monitor():
    """Return sample data while the monitor API is being developed."""
    return jsonify(
        source="sample",
        topic="/ros2log/test/temperature",
        message_type="std_msgs/msg/Float64",
        latest_message={"data": 25.4},
    )
