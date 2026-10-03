from pathlib import Path, PurePosixPath

from flask import current_app, jsonify

from backend.api import blueprint
from backend.database import get_database
from backend.rosbag_metadata import MetadataFormatError, parse_rosbag_metadata


STORAGE_ROOT = Path("/storage")
STORAGE_PREFIX = PurePosixPath("/storage")


def _error(message, status):
    return jsonify(error=message), status


def _metadata_path(output_path):
    try:
        relative_path = PurePosixPath(output_path).relative_to(STORAGE_PREFIX)
    except (TypeError, ValueError):
        raise MetadataFormatError("Recording path is outside /storage.")

    storage_root = STORAGE_ROOT.resolve()
    recording_path = (storage_root / Path(*relative_path.parts)).resolve()
    if not recording_path.is_relative_to(storage_root):
        raise MetadataFormatError("Recording path is outside /storage.")

    metadata_path = (recording_path / "metadata.yaml").resolve()
    if not metadata_path.is_relative_to(storage_root):
        raise MetadataFormatError("Metadata path is outside /storage.")
    return recording_path, metadata_path


@blueprint.get("/recordings/<int:recording_id>/metadata")
def recording_metadata(recording_id):
    row = get_database().execute(
        "SELECT id, output_path, status FROM recordings WHERE id = ?",
        (recording_id,),
    ).fetchone()
    if row is None:
        return _error("Recording was not found.", 404)
    if row["status"] == "started":
        return _error("Metadata is not available until recording finishes.", 409)

    try:
        recording_path, metadata_path = _metadata_path(row["output_path"])
    except MetadataFormatError:
        return _error("Recording path is invalid.", 422)
    except OSError:
        current_app.logger.exception("Could not resolve recording metadata path")
        return _error("Could not read recording metadata.", 500)

    try:
        if not recording_path.is_dir():
            return _error("Recording directory was not found.", 404)
        if not metadata_path.is_file():
            return _error("Recording metadata was not found.", 404)
    except OSError:
        current_app.logger.exception("Could not inspect recording metadata")
        return _error("Could not read recording metadata.", 500)

    try:
        result = parse_rosbag_metadata(metadata_path)
    except MetadataFormatError as error:
        return _error(str(error), 422)
    except OSError:
        current_app.logger.exception("Could not read recording metadata")
        return _error("Could not read recording metadata.", 500)

    result["recording"] = {
        "id": row["id"],
        "name": PurePosixPath(row["output_path"]).name,
        "status": row["status"],
    }
    return jsonify(result)
