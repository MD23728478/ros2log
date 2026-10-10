from io import BytesIO
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

import config
from backend.api import topic_record
from backend.app import create_app
from backend.database import get_database
from runner.client import Ros2BackgroundCommandError


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", "file:config_record_test?mode=memory&cache=shared")
    monkeypatch.setattr(config, "STORAGE_PATH", tmp_path / "storage")
    application = create_app()
    application.config["TESTING"] = True
    yield application
    application.extensions["database_keeper"].close()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def start_command(monkeypatch):
    mock = Mock(return_value={"state": "running"})
    monkeypatch.setattr(topic_record, "ros2_background_command_start", mock)
    return mock


def recording_yaml(output):
    return yaml.safe_dump({
        "rosbag2_recorder": {
            "ros__parameters": {
                "record": {"all_topics": True, "include_hidden_topics": True},
                "storage": {"uri": output, "storage_id": "sqlite3"},
            }
        }
    })


def upload_config(client, content, filename="config.yaml"):
    return client.post(
        "/api/record/config",
        data={"file": (BytesIO(content), filename)},
    )


def test_upload_preserves_yaml_and_returns_config_and_output_paths(app, client):
    output = app.config["STORAGE_PATH"] / "recordings" / "robot-test"
    content = recording_yaml(str(output)).encode("utf-8")

    response = upload_config(client, content)

    assert response.status_code == 201
    body = response.get_json()
    saved = Path(body["config_path"])
    assert saved.parent == app.config["STORAGE_PATH"] / "configs"
    assert saved.suffix == ".yaml"
    assert saved.read_bytes() == content
    assert body["output"] == str(output)
    assert not output.exists()
    with app.app_context():
        assert get_database().execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 0


def test_upload_uses_unique_names_and_ignores_client_path(app, client):
    content = recording_yaml(str(app.config["STORAGE_PATH"] / "robot-test")).encode()

    first = upload_config(client, content, "../../outside.yaml")
    second = upload_config(client, content, "../../outside.yaml")

    assert first.status_code == second.status_code == 201
    first_path = Path(first.get_json()["config_path"])
    second_path = Path(second.get_json()["config_path"])
    assert first_path != second_path
    assert first_path.parent == second_path.parent == app.config["STORAGE_PATH"] / "configs"
    assert first_path.read_bytes() == second_path.read_bytes() == content


@pytest.mark.parametrize("data", [{}, {"file": (BytesIO(b""), "")}])
def test_missing_file_is_rejected_without_creating_storage(app, client, data):
    response = client.post("/api/record/config", data=data)

    assert response.status_code == 400
    assert "error" in response.get_json()
    assert not app.config["STORAGE_PATH"].exists()


@pytest.mark.parametrize("content", [
    b"", b"   \n", b"record: [", b"\xff", b"[]", b"true", b"{}",
    b"rosbag2_recorder: []", b"rosbag2_recorder:\n  ros__parameters: {}",
    b"!!python/object/apply:os.system ['echo unsafe']",
])
def test_invalid_yaml_is_rejected_without_creating_storage(app, client, content):
    response = upload_config(client, content)

    assert response.status_code == 400
    assert "error" in response.get_json()
    assert not app.config["STORAGE_PATH"].exists()


@pytest.mark.parametrize("output", [None, 42, "", "  ", "relative/recording", "bad\0path"])
def test_invalid_output_path_is_rejected(app, client, output):
    response = upload_config(client, recording_yaml(output).encode())

    assert response.status_code == 400
    assert "error" in response.get_json()
    assert not app.config["STORAGE_PATH"].exists()


@pytest.mark.parametrize("target", ["outside", "sibling", "traversal", "root"])
def test_output_must_be_inside_shared_storage(app, client, target):
    storage = app.config["STORAGE_PATH"]
    outputs = {
        "outside": storage.parent / "recording",
        "sibling": storage.with_name("storage-other") / "recording",
        "traversal": storage / ".." / "recording",
        "root": storage,
    }

    response = upload_config(client, recording_yaml(str(outputs[target])).encode())

    assert response.status_code == 400
    assert not storage.exists()


def test_oversized_config_is_rejected(app, client):
    response = upload_config(client, b"x" * (1024 * 1024 + 1))

    assert response.status_code == 413
    assert not app.config["STORAGE_PATH"].exists()


def test_storage_failure_returns_json_error(app, client):
    storage = app.config["STORAGE_PATH"]
    storage.mkdir()
    (storage / "configs").write_text("not a directory")

    response = upload_config(client, recording_yaml(str(storage / "robot-test")).encode())

    assert response.status_code == 500
    assert response.get_json() == {"error": "Could not save recording configuration."}
    assert (storage / "configs").read_text() == "not a directory"


def test_output_symlink_cannot_escape_storage(app, client):
    storage = app.config["STORAGE_PATH"]
    storage.mkdir()
    (storage / "alias").symlink_to(storage.parent / "outside", target_is_directory=True)

    response = upload_config(
        client, recording_yaml(str(storage / "alias" / "recording")).encode()
    )

    assert response.status_code == 400
    assert not (storage / "configs").exists()


def test_config_directory_symlink_cannot_escape_storage(app, client):
    storage = app.config["STORAGE_PATH"]
    storage.mkdir()
    outside = storage.parent / "outside"
    outside.mkdir()
    (storage / "configs").symlink_to(outside, target_is_directory=True)

    response = upload_config(client, recording_yaml(str(storage / "recording")).encode())

    assert response.status_code == 500
    assert list(outside.iterdir()) == []


def test_deeply_nested_yaml_returns_validation_error(app, client):
    response = upload_config(client, b"[" * 2000 + b"]" * 2000)

    assert response.status_code == 400
    assert not app.config["STORAGE_PATH"].exists()


def test_uploaded_config_starts_recorder_and_persists_yaml_output(app, client, start_command):
    output = app.config["STORAGE_PATH"] / "custom-robot-recording"
    uploaded = upload_config(client, recording_yaml(str(output)).encode()).get_json()

    response = client.post("/api/record/start", json={"config_path": uploaded["config_path"]})

    assert response.status_code == 201
    assert response.get_json() == {
        "output": str(output), "display_output": str(output), "state": "running"
    }
    start_command.assert_called_once_with(
        "run", "rosbag2_transport", "recorder", "--ros-args", "-r",
        "__node:=rosbag2_recorder", "--params-file", uploaded["config_path"],
        "-p", f"storage.uri:={json.dumps(str(output))}",
        timeout_seconds=app.config["RECORDING_TIMEOUT_SECONDS"],
    )
    with app.app_context():
        row = get_database().execute(
            "SELECT output_path, topics, status, finished_at FROM recordings"
        ).fetchone()
    assert row["output_path"] == str(output)
    assert row["topics"] == "[]"
    assert row["status"] == "started"
    assert row["finished_at"] is None
    assert Path(uploaded["config_path"]).is_file()


def test_production_yaml_start_preserves_container_paths_and_displays_host_path(
    app, client, start_command, tmp_path
):
    app.config["APP_ENV"] = "production"
    app.config["RUNNER_STORAGE_PATH"] = tmp_path / "host-storage"
    output = app.config["STORAGE_PATH"] / "robot #1: test"
    content = recording_yaml(str(output)).encode()
    uploaded = upload_config(client, content).get_json()

    response = client.post("/api/record/start", json={"config_path": uploaded["config_path"]})

    assert response.status_code == 201
    assert response.get_json()["output"] == str(output)
    assert response.get_json()["display_output"] == str(tmp_path / "host-storage" / output.name)
    arguments = start_command.call_args.args
    assert arguments[-3] == uploaded["config_path"]
    assert json.loads(arguments[-1].removeprefix("storage.uri:=")) == str(output)
    assert Path(uploaded["config_path"]).read_bytes() == content
    with app.app_context():
        row = get_database().execute("SELECT output_path, status FROM recordings").fetchone()
    assert row["output_path"] == str(output)
    assert row["status"] == "started"


@pytest.mark.parametrize("config_path", [None, 42, "", [], "bad\0path", "configs/config.yaml"])
def test_invalid_config_path_does_not_call_runner(app, client, start_command, config_path):
    response = client.post("/api/record/start", json={"config_path": config_path})

    assert response.status_code == 400
    start_command.assert_not_called()
    with app.app_context():
        assert get_database().execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 0


def test_start_cannot_read_yaml_outside_configs(app, client, start_command):
    storage = app.config["STORAGE_PATH"]
    storage.mkdir()
    path = storage / "other.yaml"
    path.write_text(recording_yaml(str(storage / "recording")))

    response = client.post("/api/record/start", json={"config_path": str(path)})

    assert response.status_code == 400
    start_command.assert_not_called()


def test_missing_uploaded_config_returns_not_found(app, client, start_command):
    path = app.config["STORAGE_PATH"] / "configs" / "missing.yaml"

    response = client.post("/api/record/start", json={"config_path": str(path)})

    assert response.status_code == 404
    start_command.assert_not_called()


@pytest.mark.parametrize("content", [b"not: [yaml", b"x" * (1024 * 1024 + 1)])
def test_changed_config_is_revalidated_before_start(app, client, start_command, content):
    output = app.config["STORAGE_PATH"] / "recording"
    uploaded = upload_config(client, recording_yaml(str(output)).encode()).get_json()
    Path(uploaded["config_path"]).write_bytes(content)

    response = client.post("/api/record/start", json={"config_path": uploaded["config_path"]})

    assert response.status_code == 400
    start_command.assert_not_called()


def test_changed_output_cannot_escape_storage(app, client, start_command):
    storage = app.config["STORAGE_PATH"]
    uploaded = upload_config(client, recording_yaml(str(storage / "recording")).encode()).get_json()
    Path(uploaded["config_path"]).write_text(recording_yaml(str(storage.parent / "outside")))

    response = client.post("/api/record/start", json={"config_path": uploaded["config_path"]})

    assert response.status_code == 400
    start_command.assert_not_called()


def test_config_symlink_cannot_escape_configs(app, client, start_command):
    storage = app.config["STORAGE_PATH"]
    (storage / "configs").mkdir(parents=True)
    outside = storage / "outside.yaml"
    outside.write_text(recording_yaml(str(storage / "recording")))
    path = storage / "configs" / "link.yaml"
    path.symlink_to(outside)

    response = client.post("/api/record/start", json={"config_path": str(path)})

    assert response.status_code == 400
    start_command.assert_not_called()


def test_existing_recording_folder_is_preserved(app, client, start_command):
    output = app.config["STORAGE_PATH"] / "recording"
    output.mkdir(parents=True)
    (output / "metadata.yaml").write_text("existing recording")
    uploaded = upload_config(client, recording_yaml(str(output)).encode()).get_json()

    response = client.post("/api/record/start", json={"config_path": uploaded["config_path"]})

    assert response.status_code == 409
    start_command.assert_not_called()
    assert (output / "metadata.yaml").read_text() == "existing recording"


@pytest.mark.parametrize("status", [409, 503])
def test_failed_runner_start_removes_only_new_record(app, client, start_command, status):
    storage = app.config["STORAGE_PATH"]
    uploaded = upload_config(client, recording_yaml(str(storage / "recording")).encode()).get_json()
    start_command.side_effect = Ros2BackgroundCommandError("Runner error", status_code=status)
    with app.app_context():
        database = get_database()
        database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            (str(storage / "previous"), "[]", "finished"),
        )
        database.commit()

    response = client.post("/api/record/start", json={"config_path": uploaded["config_path"]})

    assert response.status_code == status
    with app.app_context():
        rows = get_database().execute("SELECT output_path, status FROM recordings").fetchall()
    assert [(row["output_path"], row["status"]) for row in rows] == [
        (str(storage / "previous"), "finished")
    ]
    assert Path(uploaded["config_path"]).is_file()


@pytest.mark.parametrize("first_mode", ["config", "manual"])
def test_manual_and_config_starts_share_one_active_recording(app, client, start_command, first_mode):
    storage = app.config["STORAGE_PATH"]
    uploaded = upload_config(client, recording_yaml(str(storage / "recording")).encode()).get_json()
    requests = {
        "config": {"config_path": uploaded["config_path"]},
        "manual": {"topics": ["/ros2log/test/temperature"]},
    }
    first = client.post("/api/record/start", json=requests[first_mode])
    second_mode = "manual" if first_mode == "config" else "config"

    second = client.post("/api/record/start", json=requests[second_mode])

    assert first.status_code == 201
    assert second.status_code == 409
    assert start_command.call_count == 1
    with app.app_context():
        assert get_database().execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1


def test_saved_recording_path_cannot_be_reused(app, client, start_command):
    output = app.config["STORAGE_PATH"] / "recording"
    uploaded = upload_config(client, recording_yaml(str(output)).encode()).get_json()
    with app.app_context():
        database = get_database()
        database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            (str(output), "[]", "finished"),
        )
        database.commit()

    response = client.post("/api/record/start", json={"config_path": uploaded["config_path"]})

    assert response.status_code == 409
    start_command.assert_not_called()
    with app.app_context():
        assert get_database().execute("SELECT status FROM recordings").fetchone()["status"] == "finished"
