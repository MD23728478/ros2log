import json
import re

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
PREFIX_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}")


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
    if not isinstance(body, dict):
        return jsonify(error="Provide a JSON object."), 400

    topics = body.get("topics")
    prefix = body.get("prefix", "")
    duration_seconds = body.get("duration_seconds")

    if not isinstance(topics, list) or not topics or not all(
        isinstance(topic, str) and TOPIC_NAME_PATTERN.fullmatch(topic) for topic in topics
    ):
        return jsonify(error="Provide a non-empty list of valid topic names."), 400

    if not isinstance(prefix, str):
        return jsonify(error="Prefix must be a string."), 400
    prefix = prefix.strip()
    if prefix and not PREFIX_PATTERN.fullmatch(prefix):
        return jsonify(
            error="Prefix must contain 1-32 letters, numbers, hyphens, or underscores."
        ), 400

    if duration_seconds is not None:
        if (
            not isinstance(duration_seconds, int)
            or isinstance(duration_seconds, bool)
            or duration_seconds <= 0
        ):
            return jsonify(
                error="Duration must be a positive whole number of seconds."
            ), 400

        if duration_seconds > current_app.config["RECORDING_TIMEOUT_SECONDS"]:
            return jsonify(
                error="Duration cannot exceed the maximum recording time."
            ), 400

    recording_timeout = (
        duration_seconds
        if duration_seconds is not None
        else current_app.config["RECORDING_TIMEOUT_SECONDS"]
    )

    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    recording_name = f"recording-{timestamp}"
    if prefix:
        recording_name = f"{prefix}-{recording_name}"
    output_path = str(current_app.config["STORAGE_PATH"] / recording_name)
    database = get_database()
    database.execute(
        "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
        (output_path, json.dumps(topics), "started"),
    )
    database.commit()

    try:
        result = ros2_background_command_start(
            "bag", "record", "--output", output_path, "--topics", *topics,
            timeout_seconds=recording_timeout,
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
            if result.get("termination_reason") in ("manual", "timeout")
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
