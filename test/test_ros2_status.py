import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from unittest.mock import Mock

import pytest

import config
from backend.api import ros2
from backend.app import create_app
from backend.database import get_database
from runner.client import Ros2CommandError
from runner.server import RunnerServer


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", "file:ros2_status_test?mode=memory&cache=shared")
    application = create_app()
    application.config["TESTING"] = True
    yield application
    application.extensions["database_keeper"].close()


@pytest.fixture
def client(app):
    return app.test_client()


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


@pytest.fixture
def http_runner(app, monkeypatch):
    probe = Mock(return_value={"return_code": 0, "stdout": "/rosout\n", "stderr": ""})
    monkeypatch.setattr("runner.server.run_command", probe)
    popen = subprocess.Popen
    program = (
        "import signal, sys, time; "
        "signal.signal(signal.SIGINT, lambda *_: sys.exit(0)); "
        "print('ready', flush=True); time.sleep(60)"
    )
    monkeypatch.setattr(
        "runner.server.subprocess.Popen",
        lambda arguments, **options: popen([sys.executable, "-c", program], **options),
    )
    server = RunnerServer(("127.0.0.1", 0))
    thread = Thread(target=server.serve_forever)
    thread.start()
    app.config["ROS2_RUNNER_ADDRESS"] = "127.0.0.1"
    app.config["ROS2_RUNNER_PORT"] = server.server_port
    try:
        yield server, probe
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def start_recording(client, server):
    response = client.post(
        "/api/record/start", json={"topics": ["/rosout"], "prefix": "status-test"},
    )
    assert response.status_code == 201
    command = server.background_command.command
    deadline = time.monotonic() + 3
    while "ready" not in command.result()["stdout"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "ready" in command.result()["stdout"]
    return response.get_json()["output"], command


@pytest.mark.parametrize("failure", ["command", "timeout", "health"])
def test_status_recovers_without_interrupting_recording(
    app, client, http_runner, monkeypatch, failure,
):
    server, probe = http_runner
    output, recording = start_recording(client, server)
    assert client.get("/api/ros2/status").get_json() == {"status": "available"}
    health = ros2.ros2_runner_is_healthy
    if failure == "health":
        monkeypatch.setattr(ros2, "ros2_runner_is_healthy", lambda: False)
    elif failure == "timeout":
        probe.side_effect = subprocess.TimeoutExpired(["ros2", "topic", "list"], 3)
    else:
        probe.return_value = {"return_code": 1, "stdout": "", "stderr": "ROS error"}

    expected = "runner_unavailable" if failure == "health" else "ros2_unavailable"
    assert client.get("/api/ros2/status").get_json() == {"status": expected}
    assert server.background_command.command is recording
    assert recording.process.poll() is None
    assert client.get("/api/record/status").get_json()["state"] == "running"
    with app.app_context():
        row = get_database().execute("SELECT * FROM recordings").fetchone()
        assert row["output_path"] == output
        assert row["status"] == "started"
        assert row["finished_at"] is None

    monkeypatch.setattr(ros2, "ros2_runner_is_healthy", health)
    probe.side_effect = None
    probe.return_value = {"return_code": 0, "stdout": "", "stderr": ""}
    assert client.get("/api/ros2/status").get_json() == {"status": "available"}
    response = client.post("/api/record/stop")
    assert response.status_code == 200
    result = response.get_json()
    assert result["state"] == "finished"
    assert result["return_code"] == 0
    assert result["termination_reason"] == "manual"
    assert result["forced"] is False
    with app.app_context():
        row = get_database().execute("SELECT * FROM recordings").fetchone()
        assert row["status"] == "finished"
        assert row["finished_at"] is not None


def test_pending_status_check_does_not_block_recording_stop(app, client, http_runner):
    server, probe = http_runner
    start_recording(client, server)
    started = Event()
    release = Event()

    def pending_probe(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return {"return_code": 0, "stdout": "", "stderr": ""}

    def check_status():
        with app.test_client() as other_client:
            return other_client.get("/api/ros2/status")

    probe.side_effect = pending_probe
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(check_status)
        try:
            assert started.wait(3)
            response = client.post("/api/record/stop")
            assert response.status_code == 200
            assert response.get_json()["state"] == "finished"
            assert response.get_json()["return_code"] == 0
            assert not pending.done()
        finally:
            release.set()
        assert pending.result(timeout=3).get_json() == {"status": "available"}
