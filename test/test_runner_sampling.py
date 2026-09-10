import json
import subprocess
import sys
import time
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import config
from backend.app import create_app
from runner.client import Ros2CommandError, ros2_command
from runner.server import CommandHandler, run_command


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
