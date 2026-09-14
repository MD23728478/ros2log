from unittest.mock import Mock

import pytest

import config
from backend.api import topic_record
from backend.app import create_app
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


def test_start_recording_returns_output_path_and_state(client, start_command):
    start_command.return_value = background_result(state="running")
    response = client.post(
        "/api/record/start", json={"topics": ["/ros2log/test/temperature"]}
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["state"] == "running"
    assert body["output"].startswith("/storage/recording-")
    start_command.assert_called_once()
    called_args = start_command.call_args.args
    assert called_args[:4] == ("bag", "record", "--output", body["output"])
    assert "/ros2log/test/temperature" in called_args


@pytest.mark.parametrize(
    "body",
    [{}, {"topics": []}, {"topics": "not-a-list"}, {"topics": ["bad name"]}, {"topics": [123]}],
)
def test_invalid_topics_does_not_call_runner(client, start_command, body):
    response = client.post("/api/record/start", json=body)
    assert response.status_code == 400
    assert "error" in response.get_json()
    start_command.assert_not_called()


def test_start_conflict_when_already_recording(client, start_command):
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


def test_status_returns_current_state(client, status_command):
    status_command.return_value = background_result(state="running")
    response = client.get("/api/record/status")
    assert response.status_code == 200
    assert response.get_json()["state"] == "running"


def test_stop_returns_finished_state(client, stop_command):
    stop_command.return_value = background_result(
        state="finished", return_code=0, termination_reason="manual"
    )
    response = client.post("/api/record/stop")
    assert response.status_code == 200
    body = response.get_json()
    assert body["state"] == "finished"
    assert body["termination_reason"] == "manual"


@pytest.mark.parametrize(
    "route, method",
    [("/api/record/status", "get"), ("/api/record/stop", "post")],
)
def test_runner_unavailable_returns_error(client, status_command, stop_command, route, method):
    error = Ros2BackgroundCommandError("ROS 2 runner is unavailable")
    status_command.side_effect = error
    stop_command.side_effect = error
    response = getattr(client, method)(route)
    assert response.status_code == 503
    assert "error" in response.get_json()