from unittest.mock import Mock

import pytest

import config
from backend.api import ros2
from backend.app import create_app
from runner.client import Ros2CommandError


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", "file:ros2_status_test?mode=memory&cache=shared")
    application = create_app()
    application.config["TESTING"] = True
    yield application.test_client()
    application.extensions["database_keeper"].close()


@pytest.fixture
def runner_health(monkeypatch):
    mock = Mock(return_value=True)
    monkeypatch.setattr(ros2, "ros2_runner_is_healthy", mock)
    return mock


@pytest.fixture
def command(monkeypatch):
    mock = Mock()
    monkeypatch.setattr(ros2, "ros2_command", mock)
    return mock


@pytest.mark.parametrize("stdout", ["/rosout\n", ""])
def test_ros2_available_with_or_without_topics(client, runner_health, command, stdout):
    command.return_value = {"return_code": 0, "stdout": stdout, "stderr": ""}

    response = client.get("/api/ros2/status")

    assert response.status_code == 200
    assert response.get_json() == {"status": "available"}
    assert response.headers["Cache-Control"] == "no-store"
    command.assert_called_once_with(
        "topic", "list", "--no-daemon", "--spin-time", "0.5",
        timeout_seconds=3,
    )


def test_unavailable_runner_skips_ros2_command(client, runner_health, command):
    runner_health.return_value = False

    response = client.get("/api/ros2/status")

    assert response.status_code == 200
    assert response.get_json() == {"status": "runner_unavailable"}
    assert response.headers["Cache-Control"] == "no-store"
    command.assert_not_called()


def test_failed_ros2_command_reports_ros2_unavailable(client, runner_health, command):
    command.return_value = {"return_code": 1, "stdout": "", "stderr": "ROS error"}

    response = client.get("/api/ros2/status")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ros2_unavailable"}


def test_ros2_timeout_reports_ros2_unavailable(client, runner_health, command):
    command.side_effect = Ros2CommandError("ROS 2 command timed out")

    response = client.get("/api/ros2/status")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ros2_unavailable"}


def test_runner_disappearing_during_check_reports_runner_unavailable(
    client, runner_health, command,
):
    runner_health.side_effect = [True, False]
    command.side_effect = Ros2CommandError("Runner unavailable")

    response = client.get("/api/ros2/status")

    assert response.status_code == 200
    assert response.get_json() == {"status": "runner_unavailable"}


@pytest.mark.parametrize(
    "healthy, http_status, status", [(True, 200, "ok"), (False, 503, "unavailable")],
)
def test_existing_health_response_is_preserved(
    client, runner_health, command, healthy, http_status, status,
):
    runner_health.return_value = healthy

    response = client.get("/api/ros2/health")

    assert response.status_code == http_status
    assert response.get_json() == {"status": status}
    command.assert_not_called()
