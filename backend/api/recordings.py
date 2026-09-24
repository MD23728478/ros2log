import re
import shutil
from pathlib import Path

from flask import jsonify, request

from backend.api import blueprint
from backend.database import get_database


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RECORDING_NAME_PATTERN = re.compile(r"^[^/\\\0]+$")


def _recording_path(output_path):
    return PROJECT_ROOT / output_path.lstrip("/")


def _load_recording(recording_id):
    row = get_database().execute(
        "SELECT id, output_path, topics, status FROM recordings WHERE id = ?",
        (recording_id,),
    ).fetchone()
    return row


def _json_error(message, status):
    return jsonify(error=message), status


@blueprint.post("/recordings/<int:recording_id>/rename")
def rename_recording(recording_id):
    body = request.get_json(silent=True) or {}
    new_name = str(body.get("name", "")).strip()

    if not new_name:
        return _json_error("Provide a new recording name.", 400)
    if new_name in {".", ".."} or not RECORDING_NAME_PATTERN.fullmatch(new_name):
        return _json_error("Provide a valid recording name.", 400)

    database = get_database()
    row = _load_recording(recording_id)
    if row is None:
        return _json_error("Recording was not found.", 404)

    current_path = _recording_path(row["output_path"])
    target_path = current_path.with_name(new_name)
    target_output_path = f"/storage/{new_name}"

    if target_path.exists() and target_path != current_path:
        return _json_error("A recording with that name already exists.", 409)

    try:
        if current_path.exists() and current_path != target_path:
            current_path.rename(target_path)
    except OSError:
        return _json_error("Could not rename the recording folder.", 502)

    database.execute(
        "UPDATE recordings SET output_path = ? WHERE id = ?",
        (target_output_path, recording_id),
    )
    database.commit()

    return jsonify(
        id=recording_id,
        name=new_name,
        output_path=target_output_path,
    )


@blueprint.post("/recordings/<int:recording_id>/delete")
def delete_recording(recording_id):
    database = get_database()
    row = _load_recording(recording_id)
    if row is None:
        return _json_error("Recording was not found.", 404)

    recording_path = _recording_path(row["output_path"])
    if recording_path.exists():
        try:
            shutil.rmtree(recording_path)
        except OSError:
            return _json_error("Could not delete the recording folder.", 502)

    database.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
    database.commit()

    return jsonify(deleted=True, id=recording_id)