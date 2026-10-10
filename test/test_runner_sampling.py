import json
import subprocess
import sys
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

import pytest

import config
from backend.app import create_app
from runner.client import Ros2CommandError, ros2_command
from runner.server import BackgroundCommandSlot, CommandHandler, run_command


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", "file:sampling_test?mode=memory&cache=shared")
    application = create_app()
    yield application
    application.extensions["database_keeper"].close()


@pytest.fixture
def http_runner(app):
    server = ThreadingHTTPServer(("127.0.0.1", 0), CommandHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    app.config["ROS2_RUNNER_ADDRESS"] = "127.0.0.1"
    app.config["ROS2_RUNNER_PORT"] = server.server_port
    try:
        yield f"http://127.0.0.1:{server.server_port}/command"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_finite_command_preserves_exit_code_and_response(monkeypatch):
    def subprocess_run(arguments, **options):
        assert arguments == ["ros2", "node", "list"]
        assert options["shell"] is False
        assert options["timeout"] == 2
        return subprocess.CompletedProcess(arguments, 3, "partial\n", "failure\n")

    monkeypatch.setattr("runner.server.subprocess.run", subprocess_run)
    assert run_command(["node", "list"], 2) == {
        "return_code": 3, "stdout": "partial\n", "stderr": "failure\n"
    }


def test_finite_command_uses_configured_ros2_path(monkeypatch):
    monkeypatch.setattr(config, "ROS2_EXECUTABLE_PATH", "/opt/ros/bin/ros2")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr("runner.server.subprocess.run", run)

    run_command(["node", "list"], 2)

    assert run.call_args.args[0] == ["/opt/ros/bin/ros2", "node", "list"]


@pytest.mark.parametrize("configured_path, executable", [
    (None, "ros2"),
    ("/opt/ros/bin/ros2", "/opt/ros/bin/ros2"),
])
def test_background_command_uses_ros2_path(
    monkeypatch, configured_path, executable,
):
    monkeypatch.setattr(config, "ROS2_EXECUTABLE_PATH", configured_path)
    popen = Mock()
    command = Mock()
    command.result.return_value = {"state": "running"}
    monkeypatch.setattr("runner.server.subprocess.Popen", popen)
    monkeypatch.setattr("runner.server.BackgroundCommand", Mock(return_value=command))

    assert BackgroundCommandSlot().start(["bag", "record"], 10) == {"state": "running"}

    assert popen.call_args.args[0] == [executable, "bag", "record"]


def test_production_recording_uses_host_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "RUNNER_STORAGE_PATH", tmp_path / "bags")
    popen = Mock()
    command = Mock()
    command.result.return_value = {"state": "running"}
    monkeypatch.setattr("runner.server.subprocess.Popen", popen)
    monkeypatch.setattr("runner.server.BackgroundCommand", Mock(return_value=command))

    arguments = ["bag", "record", "--output", "/storage/recording-1", "--topics", "/chatter"]
    BackgroundCommandSlot().start(arguments, 10)

    assert popen.call_args.args[0] == [
        "ros2", "bag", "record", "--output", str(tmp_path / "bags" / "recording-1"),
        "--topics", "/chatter",
    ]
    assert arguments[3] == "/storage/recording-1"
    assert (tmp_path / "bags").is_dir()


@pytest.mark.parametrize("host_storage", ["relative", "absolute"])
@pytest.mark.parametrize("quoted", [False, True])
def test_production_yaml_recording_maps_config_and_output_paths(
    monkeypatch, tmp_path, host_storage, quoted
):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "__file__", str(tmp_path / "project" / "config.py"))
    configured = tmp_path / "bags" if host_storage == "absolute" else Path("bags")
    monkeypatch.setattr(config, "RUNNER_STORAGE_PATH", configured)
    host_root = configured if configured.is_absolute() else tmp_path / "project" / configured
    output = "/storage/robot #1: test"
    parameter = json.dumps(output) if quoted else output
    arguments = [
        "run", "rosbag2_transport", "recorder", "--ros-args", "-r",
        "__node:=rosbag2_recorder", "--params-file", "/storage/configs/upload.yaml",
        "-p", f"storage.uri:={parameter}",
    ]
    original = arguments.copy()
    popen = Mock()
    command = Mock()
    command.result.return_value = {"state": "running"}
    monkeypatch.setattr("runner.server.subprocess.Popen", popen)
    monkeypatch.setattr("runner.server.BackgroundCommand", Mock(return_value=command))

    BackgroundCommandSlot().start(arguments, 10)

    called = popen.call_args.args[0]
    assert called[8] == str(host_root / "configs" / "upload.yaml")
    assert json.loads(called[-1].removeprefix("storage.uri:=")) == str(host_root / "robot #1: test")
    assert arguments == original
    assert host_root.is_dir()


def test_development_yaml_recording_keeps_shared_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "APP_ENV", "development")
    arguments = [
        "run", "rosbag2_transport", "recorder", "--ros-args",
        "--params-file", "/storage/configs/upload.yaml", "-p", 'storage.uri:="/storage/robot"',
    ]
    popen = Mock()
    command = Mock()
    command.result.return_value = {"state": "running"}
    monkeypatch.setattr("runner.server.subprocess.Popen", popen)
    monkeypatch.setattr("runner.server.BackgroundCommand", Mock(return_value=command))

    BackgroundCommandSlot().start(arguments, 10)

    assert popen.call_args.args[0] == ["ros2", *arguments]


@pytest.mark.parametrize("output", [b"average rate: 2.0\n", "average rate: 2.0\n", None])
def test_sampling_preserves_timeout_output(monkeypatch, output):
    def subprocess_run(arguments, **options):
        assert options["env"]["PYTHONUNBUFFERED"] == "1"
        raise subprocess.TimeoutExpired(
            arguments, options["timeout"], output=output, stderr=b"notice"
        )

    monkeypatch.setattr("runner.server.subprocess.run", subprocess_run)
    result = run_command(["topic", "hz", "/test"], 2, capture_on_timeout=True)
    assert result == {
        "return_code": 124,
        "stdout": "average rate: 2.0\n" if output is not None else "",
        "stderr": "notice",
        "timed_out": True,
    }


def test_sampling_reports_early_command_failure(monkeypatch):
    monkeypatch.setattr(
        "runner.server.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "bad topic"),
    )
    result = run_command(["topic", "hz", "/test"], 2, capture_on_timeout=True)
    assert result == {
        "return_code": 1, "stdout": "", "stderr": "bad topic", "timed_out": False
    }


def test_sampling_stops_a_real_process_and_keeps_its_output(monkeypatch):
    actual_run = subprocess.run

    def run_python_probe(arguments, **options):
        return actual_run(
            [sys.executable, "-c", "import time; print('average rate: 2.0'); time.sleep(60)"],
            **options,
        )

    monkeypatch.setattr("runner.server.subprocess.run", run_python_probe)
    started = time.monotonic()
    result = run_command(["topic", "hz", "/test"], 1.5, capture_on_timeout=True)
    assert time.monotonic() - started < 10
    assert result["timed_out"] is True
    assert result["stdout"].strip() == "average rate: 2.0"


def test_normal_command_timeout_remains_an_http_error(app, http_runner, monkeypatch):
    def subprocess_run(arguments, **options):
        raise subprocess.TimeoutExpired(arguments, options["timeout"], output=b"partial")

    monkeypatch.setattr("runner.server.subprocess.run", subprocess_run)
    with app.app_context(), pytest.raises(Ros2CommandError, match="timed out"):
        ros2_command("node", "list")


@pytest.mark.parametrize("capture", ["true", 1, None])
def test_runner_rejects_invalid_capture_flag(http_runner, monkeypatch, capture):
    def unexpected_command(*args, **kwargs):
        pytest.fail("Invalid request started a process")

    monkeypatch.setattr("runner.server.run_command", unexpected_command)
    request = Request(
        http_runner,
        data=json.dumps({
            "arguments": ["topic", "hz", "/test"], "capture_on_timeout": capture
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=2)
    assert error.value.code == 400
    error.value.close()


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf")])
def test_client_rejects_unbounded_or_invalid_duration(app, timeout):
    with app.app_context(), pytest.raises(Ros2CommandError, match="timeout"):
        ros2_command("topic", "hz", "/test", timeout_seconds=timeout, capture_on_timeout=True)


def test_client_rejects_invalid_capture_flag(app):
    with app.app_context(), pytest.raises(Ros2CommandError, match="boolean"):
        ros2_command("topic", "hz", "/test", capture_on_timeout="yes")


def test_client_requires_sampling_response_from_runner(app, http_runner, monkeypatch):
    monkeypatch.setattr(
        "runner.server.run_command",
        lambda *args, **kwargs: {"return_code": 0, "stdout": "", "stderr": ""},
    )
    with app.app_context(), pytest.raises(Ros2CommandError, match="invalid response"):
        ros2_command("topic", "hz", "/test", capture_on_timeout=True)
