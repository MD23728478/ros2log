import json
import re
from datetime import datetime, timezone

from flask import current_app, jsonify, request

from backend.api import blueprint
from backend.database import get_database
from runner.client import (
    Ros2BackgroundCommandError,
    ros2_background_command_start,
    ros2_background_command_status,
    ros2_background_command_stop,
)


TOPIC_NAME_PATTERN = re.compile(
    r"/[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*"
)


def _complete_latest_recording(status):
    database = get_database()
    database.execute(
        """
        UPDATE recordings
        SET status = ?, finished_at = CURRENT_TIMESTAMP
        WHERE id = (
            SELECT id FROM recordings
            WHERE status = 'started'
            ORDER BY id DESC
            LIMIT 1
        )
        """,
        (status,),
    )
    database.commit()


@blueprint.post("/record/start")
def record_start():
    body = request.get_json(silent=True) or {}
    topics = body.get("topics")

    if not isinstance(topics, list) or not topics or not all(
        isinstance(topic, str) and TOPIC_NAME_PATTERN.fullmatch(topic) for topic in topics
    ):
        return jsonify(error="Provide a non-empty list of valid topic names."), 400

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_path = f"/storage/recording-{timestamp}"
    database = get_database()
    database.execute(
        "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
        (output_path, json.dumps(topics), "started"),
    )
    database.commit()

    try:
        result = ros2_background_command_start(
            "bag", "record", "--output", output_path, "--topics", *topics,
            timeout_seconds=current_app.config["RECORDING_TIMEOUT_SECONDS"],
        )
    except Ros2BackgroundCommandError as error:
        database.execute("DELETE FROM recordings WHERE output_path = ?", (output_path,))
        database.commit()
        status = error.status_code or 503
        return jsonify(error=str(error)), status

    return jsonify(output=output_path, **result), 201


@blueprint.get("/record/status")
def record_status():
    try:
        result = ros2_background_command_status()
    except Ros2BackgroundCommandError as error:
        _complete_latest_recording("failed")
        status = error.status_code or 503
        return jsonify(error=str(error)), status

    if result.get("state") == "finished":
        status = (
            "finished"
            if result.get("termination_reason") == "manual"
            and result.get("return_code") == 0
            else "failed"
        )
        _complete_latest_recording(status)

    return jsonify(result)


@blueprint.post("/record/stop")
def record_stop():
    try:
        result = ros2_background_command_stop()
    except Ros2BackgroundCommandError as error:
        _complete_latest_recording("failed")
        status = error.status_code or 503
        return jsonify(error=str(error)), status

    if result.get("state") == "finished" and result.get("return_code") == 0:
        _complete_latest_recording("finished")

    return jsonify(result)
