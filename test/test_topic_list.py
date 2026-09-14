from unittest.mock import Mock

import pytest

import config
from backend.api import topic_list
from backend.app import create_app
from runner.client import Ros2CommandError


def command_result(stdout="", return_code=0, stderr=""):
    return {"return_code": return_code, "stdout": stdout, "stderr": stderr}


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", "file:topic_list_test?mode=memory&cache=shared")
    application = create_app()
    application.config["TESTING"] = True
    yield application
    application.extensions["database_keeper"].close()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def command(monkeypatch):
    mock = Mock()
    monkeypatch.setattr(topic_list, "ros2_command", mock)
    return mock


def test_returns_topic_names(client, command):
    command.return_value = command_result(
        "/parameter_events\n/ros2log/test/battery\n/rosout\n"
    )
    response = client.get("/api/topics")
    assert response.status_code == 200
    assert response.get_json() == {
        "topics": ["/parameter_events", "/ros2log/test/battery", "/rosout"]
    }
    command.assert_called_once_with(
        "topic", "--include-hidden-topics", "list"
    )


def test_ros2_command_failure_returns_502(client, command):
    command.return_value = command_result(return_code=1, stderr="Discovery failed")
    response = client.get("/api/topics")
    assert response.status_code == 502
    assert "error" in response.get_json()


def test_runner_unavailable_returns_503(client, command):
    command.side_effect = Ros2CommandError("Runner unavailable")
    response = client.get("/api/topics")
    assert response.status_code == 503
    assert response.get_json() == {"error": "Runner unavailable"}