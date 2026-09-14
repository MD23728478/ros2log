from flask import jsonify
from backend.api import blueprint
from runner.client import Ros2CommandError, ros2_command

@blueprint.get("/topics")
def topics():
    try:
        result = ros2_command("topic", "--include-hidden-topics", "list")
    except Ros2CommandError as error:
        return jsonify(error=str(error)), 503

    if result["return_code"] != 0:
        return jsonify(error="Could not list ROS 2 topics."), 502

    topic_names = result["stdout"].split()
    return jsonify(topics=topic_names)