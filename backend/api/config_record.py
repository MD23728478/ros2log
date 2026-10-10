from pathlib import Path
from uuid import uuid4

import yaml
from flask import current_app, jsonify, request

from backend.api import blueprint


MAX_CONFIG_BYTES = 1024 * 1024


def _recording_output(content):
    try:
        configuration = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError, RecursionError):
        raise ValueError("Provide valid UTF-8 YAML.") from None

    try:
        output = configuration["rosbag2_recorder"]["ros__parameters"]["storage"]["uri"]
    except (KeyError, TypeError):
        raise ValueError(
            "YAML must define rosbag2_recorder.ros__parameters.storage.uri."
        ) from None

    if not isinstance(output, str) or not output.strip() or "\0" in output:
        raise ValueError("Recording path must be a non-empty string.")

    storage = current_app.config["STORAGE_PATH"]
    path = Path(output)
    resolved = path.resolve()
    root = storage.resolve()
    if (
        not path.is_absolute()
        or not path.is_relative_to(storage)
        or resolved == root
        or not resolved.is_relative_to(root)
    ):
        raise ValueError(f"Recording path must be a folder inside {storage}.")
    return str(path)


def load_recording_config(config_path):
    if not isinstance(config_path, str) or not config_path or "\0" in config_path:
        raise ValueError("Provide the path of an uploaded configuration.")

    path = Path(config_path)
    storage = current_app.config["STORAGE_PATH"]
    directory = storage / "configs"
    if (
        path.parent != directory
        or not directory.resolve().is_relative_to(storage.resolve())
        or not path.resolve().is_relative_to(directory.resolve())
    ):
        raise ValueError("Configuration must be inside the shared configs folder.")
    if not path.is_file():
        raise FileNotFoundError("Uploaded configuration was not found.")

    with path.open("rb") as config_file:
        content = config_file.read(MAX_CONFIG_BYTES + 1)
    if len(content) > MAX_CONFIG_BYTES:
        raise ValueError("YAML file cannot exceed 1 MB.")
    output = _recording_output(content)
    if Path(output).exists():
        raise FileExistsError("The recording output path already exists.")
    return str(path), output


@blueprint.post("/record/config")
def upload_recording_config():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(error="Provide a YAML file."), 400

    content = upload.read(MAX_CONFIG_BYTES + 1)
    if len(content) > MAX_CONFIG_BYTES:
        return jsonify(error="YAML file cannot exceed 1 MB."), 413

    try:
        output = _recording_output(content)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except OSError:
        current_app.logger.exception("Could not resolve recording path")
        return jsonify(error="Could not access recording storage."), 500

    try:
        storage = current_app.config["STORAGE_PATH"]
        directory = storage / "configs"
        if not directory.resolve().is_relative_to(storage.resolve()):
            raise OSError("Configuration directory is outside recording storage")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid4().hex}.yaml"
        with path.open("xb") as config_file:
            config_file.write(content)
    except OSError:
        current_app.logger.exception("Could not save recording configuration")
        return jsonify(error="Could not save recording configuration."), 500

    return jsonify(config_path=str(path), output=output), 201
