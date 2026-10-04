from flask import jsonify

from backend.api import blueprint
from runner.client import Ros2CommandError, ros2_command, ros2_runner_is_healthy


@blueprint.get("/ros2/health")
def ros2_health():
    if ros2_runner_is_healthy():
        return jsonify(status="ok")

    return jsonify(status="unavailable"), 503


@blueprint.get("/ros2/status")
def ros2_status():
    status = "runner_unavailable"
    if ros2_runner_is_healthy():
        try:
            result = ros2_command(
                "topic", "list", "--no-daemon", "--spin-time", "0.5",
                timeout_seconds=3,
            )
            status = "available" if result["return_code"] == 0 else "ros2_unavailable"
        except Ros2CommandError:
            status = "ros2_unavailable"
            if not ros2_runner_is_healthy():
                status = "runner_unavailable"

    response = jsonify(status=status)
    response.headers["Cache-Control"] = "no-store"
    return response
