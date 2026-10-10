import json
import re
from pathlib import Path
from sqlite3 import IntegrityError

from flask import current_app, jsonify, request

from backend.api import blueprint
from backend.api.config_record import load_recording_config
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


def _start_recording(output_path, topics, arguments, timeout):
    database = get_database()
    try:
        cursor = database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            (output_path, json.dumps(topics), "started"),
        )
        database.commit()
    except IntegrityError:
        database.rollback()
        return jsonify(
            error="A recording is already active or this output path is already used."
        ), 409

    try:
        result = ros2_background_command_start(*arguments, timeout_seconds=timeout)
    except Ros2BackgroundCommandError as error:
        database.execute("DELETE FROM recordings WHERE id = ?", (cursor.lastrowid,))
        database.commit()
        return jsonify(error=str(error)), error.status_code or 503

    display_output = output_path
    if current_app.config["APP_ENV"] == "production":
        display_output = str(
            current_app.config["RUNNER_STORAGE_PATH"]
            / Path(output_path).relative_to(current_app.config["STORAGE_PATH"])
        )
    return jsonify(output=output_path, display_output=display_output, **result), 201


@blueprint.post("/record/start")
def record_start():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify(error="Provide a JSON object."), 400

    if "config_path" in body:
        try:
            config_path, output = load_recording_config(body["config_path"])
        except FileNotFoundError as error:
            return jsonify(error=str(error)), 404
        except FileExistsError as error:
            return jsonify(error=str(error)), 409
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except OSError:
            current_app.logger.exception("Could not read recording configuration")
            return jsonify(error="Could not read recording configuration."), 500

        return _start_recording(
            output, [],
            ["run", "rosbag2_transport", "recorder", "--ros-args", "-r",
             "__node:=rosbag2_recorder", "--params-file", config_path,
             "-p", f"storage.uri:={json.dumps(output, ensure_ascii=False)}"],
            current_app.config["RECORDING_TIMEOUT_SECONDS"],
        )

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
    return _start_recording(
        output_path, topics,
        ["bag", "record", "--output", output_path, "--topics", *topics],
        recording_timeout,
    )


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

    if result.get("state") == "finished":
        _complete_latest_recording("finished" if result.get("return_code") == 0 else "failed")

    return jsonify(result)
