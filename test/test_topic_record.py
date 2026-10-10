import json
from unittest.mock import Mock

import pytest

import config
from backend.api import topic_record
from backend.app import create_app
from backend.database import get_database
from runner.client import Ros2BackgroundCommandError


def background_result(state="running", return_code=None, **extra):
    result = {
        "state": state,
        "return_code": return_code,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "termination_reason": None,
        "forced": False,
    }
    result.update(extra)
    return result


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", "file:record_test?mode=memory&cache=shared")
    application = create_app()
    application.config["TESTING"] = True
    yield application
    application.extensions["database_keeper"].close()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def start_command(monkeypatch):
    mock = Mock()
    monkeypatch.setattr(topic_record, "ros2_background_command_start", mock)
    return mock


@pytest.fixture
def status_command(monkeypatch):
    mock = Mock()
    monkeypatch.setattr(topic_record, "ros2_background_command_status", mock)
    return mock


@pytest.fixture
def stop_command(monkeypatch):
    mock = Mock()
    monkeypatch.setattr(topic_record, "ros2_background_command_stop", mock)
    return mock


@pytest.mark.parametrize(
    "topics",
    [
        ["/ros2log/test/temperature"],
        ["/ros2log/test/temperature", "/ros2log/test/battery"],
    ],
)
def test_start_recording_returns_output_path_and_state(client, start_command, topics):
    start_command.return_value = background_result(state="running")
    response = client.post("/api/record/start", json={"topics": topics})
    assert response.status_code == 201
    body = response.get_json()
    assert body["state"] == "running"
    assert body["output"].startswith("/storage/recording-")
    start_command.assert_called_once_with(
        "bag",
        "record",
        "--output",
        body["output"],
        "--topics",
        *topics,
        timeout_seconds=config.RECORDING_TIMEOUT_SECONDS,
    )


def test_start_recording_uses_configured_storage_path(app, client, start_command, tmp_path):
    storage_path = tmp_path / "bags"
    app.config["STORAGE_PATH"] = storage_path
    start_command.return_value = background_result(state="running")

    response = client.post(
        "/api/record/start", json={"topics": ["/ros2log/test/temperature"]}
    )

    assert response.status_code == 201
    assert response.get_json()["output"].startswith(f"{storage_path}/recording-")
    assert start_command.call_args.args[3] == response.get_json()["output"]


def test_production_start_displays_host_path_without_changing_database(
    app, client, start_command, tmp_path
):
    app.config["APP_ENV"] = "production"
    app.config["RUNNER_STORAGE_PATH"] = tmp_path / "bags"
    start_command.return_value = background_result()

    response = client.post("/api/record/start", json={"topics": ["/chatter"]})

    output = response.get_json()["output"]
    assert response.get_json()["display_output"] == str(
        tmp_path / "bags" / output.removeprefix("/storage/")
    )
    with app.app_context():
        assert get_database().execute("SELECT output_path FROM recordings").fetchone()[0] == output


def test_start_recording_uses_prefix_in_output_path(app, client, start_command):
    start_command.return_value = background_result(state="running")
    topics = ["/ros2log/test/temperature"]

    response = client.post(
        "/api/record/start", json={"topics": topics, "prefix": "  Sprint_3  "}
    )

    assert response.status_code == 201
    output_path = response.get_json()["output"]
    assert output_path.startswith("/storage/Sprint_3-recording-")
    start_command.assert_called_once_with(
        "bag",
        "record",
        "--output",
        output_path,
        "--topics",
        *topics,
        timeout_seconds=config.RECORDING_TIMEOUT_SECONDS,
    )
    with app.app_context():
        saved_path = get_database().execute(
            "SELECT output_path FROM recordings"
        ).fetchone()["output_path"]
    assert saved_path == output_path


@pytest.mark.parametrize("prefix", ["", "   "])
def test_blank_prefix_keeps_default_name(client, start_command, prefix):
    start_command.return_value = background_result(state="running")

    response = client.post(
        "/api/record/start",
        json={"topics": ["/ros2log/test/temperature"], "prefix": prefix},
    )

    assert response.status_code == 201
    assert response.get_json()["output"].startswith("/storage/recording-")


@pytest.mark.parametrize(
    "prefix", ["../escape", "has space", "bad.name", "x" * 33, 123, None, ["test"]]
)
def test_invalid_prefix_does_not_start_recording(client, start_command, prefix):
    response = client.post(
        "/api/record/start",
        json={"topics": ["/ros2log/test/temperature"], "prefix": prefix},
    )

    assert response.status_code == 400
    assert "error" in response.get_json()
    start_command.assert_not_called()


def test_start_recording_persists_started_record(app, client, start_command):
    topics = ["/ros2log/test/temperature", "/ros2log/test/battery"]
    start_command.return_value = background_result(state="running")

    response = client.post("/api/record/start", json={"topics": topics})

    with app.app_context():
        row = get_database().execute(
            "SELECT output_path, topics, status, finished_at FROM recordings"
        ).fetchone()

    assert row["output_path"] == response.get_json()["output"]
    assert json.loads(row["topics"]) == topics
    assert row["status"] == "started"
    assert row["finished_at"] is None


@pytest.mark.parametrize(
    "body",
    [{}, {"topics": []}, {"topics": "not-a-list"}, {"topics": ["bad name"]}, {"topics": [123]}],
)
def test_invalid_topics_does_not_call_runner(client, start_command, body):
    response = client.post("/api/record/start", json=body)
    assert response.status_code == 400
    assert "error" in response.get_json()
    start_command.assert_not_called()


def test_start_conflict_when_already_recording(app, client, start_command):
    # The runner itself enforces one recording at a time; this checks that
    # its 409 passes through unchanged rather than becoming a generic 503.
    start_command.side_effect = Ros2BackgroundCommandError(
        "Background command is already active", status_code=409
    )
    response = client.post(
        "/api/record/start", json={"topics": ["/ros2log/test/temperature"]}
    )
    assert response.status_code == 409
    assert "error" in response.get_json()

    with app.app_context():
        count = get_database().execute("SELECT COUNT(*) FROM recordings").fetchone()[0]

    assert count == 0


def test_status_returns_current_state(client, status_command):
    status_command.return_value = background_result(state="running")
    response = client.get("/api/record/status")
    assert response.status_code == 200
    assert response.get_json()["state"] == "running"


def test_status_marks_unexpectedly_finished_recording_failed(
    app, client, status_command
):
    with app.app_context():
        database = get_database()
        database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            ("/storage/recording-test", "[]", "started"),
        )
        database.commit()

    status_command.return_value = background_result(state="finished", return_code=1)
    response = client.get("/api/record/status")

    with app.app_context():
        row = get_database().execute(
            "SELECT status, finished_at FROM recordings"
        ).fetchone()

    assert response.status_code == 200
    assert row["status"] == "failed"
    assert row["finished_at"] is not None


def test_status_reconciles_successful_manual_stop_as_finished(
    app, client, status_command
):
    with app.app_context():
        database = get_database()
        database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            ("/storage/recording-test", "[]", "started"),
        )
        database.commit()

    status_command.return_value = background_result(
        state="finished", return_code=0, termination_reason="manual"
    )
    response = client.get("/api/record/status")

    with app.app_context():
        status = get_database().execute(
            "SELECT status FROM recordings"
        ).fetchone()["status"]

    assert response.status_code == 200
    assert status == "finished"


def test_stop_returns_finished_state(client, stop_command):
    stop_command.return_value = background_result(
        state="finished", return_code=0, termination_reason="manual"
    )
    response = client.post("/api/record/stop")
    assert response.status_code == 200
    body = response.get_json()
    assert body["state"] == "finished"
    assert body["termination_reason"] == "manual"


def test_stop_marks_latest_started_recording_finished(app, client, stop_command):
    with app.app_context():
        database = get_database()
        database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            ("/storage/recording-test", "[]", "started"),
        )
        database.commit()

    stop_command.return_value = background_result(
        state="finished", return_code=0, termination_reason="manual"
    )
    response = client.post("/api/record/stop")

    with app.app_context():
        row = get_database().execute(
            "SELECT status, finished_at FROM recordings"
        ).fetchone()

    assert response.status_code == 200
    assert row["status"] == "finished"
    assert row["finished_at"] is not None


@pytest.mark.parametrize(
    "route, method",
    [("/api/record/status", "get"), ("/api/record/stop", "post")],
)
def test_runner_unavailable_fails_active_recording(
    app, client, status_command, stop_command, route, method
):
    with app.app_context():
        database = get_database()
        database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            ("/storage/recording-test", "[]", "started"),
        )
        database.commit()

    error = Ros2BackgroundCommandError("ROS 2 runner is unavailable")
    status_command.side_effect = error
    stop_command.side_effect = error
    response = getattr(client, method)(route)

    with app.app_context():
        row = get_database().execute(
            "SELECT status, finished_at FROM recordings"
        ).fetchone()

    assert response.status_code == 503
    assert "error" in response.get_json()
    assert row["status"] == "failed"
    assert row["finished_at"] is not None

def test_start_recording_uses_custom_duration(client, start_command):
    start_command.return_value = background_result(state="running")
    topics = ["/ros2log/test/temperature"]

    response = client.post(
        "/api/record/start",
        json={"topics": topics, "duration_seconds": 120},
    )

    assert response.status_code == 201

    output_path = response.get_json()["output"]

    start_command.assert_called_once_with(
        "bag",
        "record",
        "--output",
        output_path,
        "--topics",
        *topics,
        timeout_seconds=120,
    )

@pytest.mark.parametrize(
    "duration",
    [0, -1, 1.5, "60", True],
)
def test_invalid_recording_duration_does_not_start(
    client, start_command, duration
):
    response = client.post(
        "/api/record/start",
        json={
            "topics": ["/ros2log/test/temperature"],
            "duration_seconds": duration,
        },
    )

    assert response.status_code == 400
    assert "error" in response.get_json()
    start_command.assert_not_called()

def test_recording_duration_cannot_exceed_24_hours(client, start_command):
    response = client.post(
        "/api/record/start",
        json={
            "topics": ["/ros2log/test/temperature"],
            "duration_seconds": 86401,
        },
    )

    assert response.status_code == 400
    assert "error" in response.get_json()
    start_command.assert_not_called()

def test_status_reconciles_successful_timeout_as_finished(
    app, client, status_command
):
    with app.app_context():
        database = get_database()
        database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            ("/storage/recording-test", "[]", "started"),
        )
        database.commit()

    status_command.return_value = background_result(
        state="finished",
        return_code=0,
        termination_reason="timeout",
    )

    response = client.get("/api/record/status")

    with app.app_context():
        status = get_database().execute(
            "SELECT status FROM recordings"
        ).fetchone()["status"]

    assert response.status_code == 200
    assert status == "finished"
