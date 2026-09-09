from flask import jsonify

from backend.api import blueprint
from runner.client import ros2_runner_is_healthy


@blueprint.get("/ros2/health")
def ros2_health():
    if ros2_runner_is_healthy():
        return jsonify(status="ok")

    return jsonify(status="unavailable"), 503
