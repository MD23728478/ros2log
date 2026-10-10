from io import BytesIO
from pathlib import Path

import pytest
import yaml

import config
from backend.app import create_app
from backend.database import get_database


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
