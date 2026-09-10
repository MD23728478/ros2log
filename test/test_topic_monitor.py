import subprocess
from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import Mock

import pytest

import config
from backend.api import topic_monitor as monitor
from backend.app import create_app
from runner.client import Ros2CommandError
from runner.server import CommandHandler


HZ = "average rate: 2.000\n\tmin: 0.49s max: 0.51s std dev: 0.01s window: 8\n"
BW = "32 B/s from 8 messages\n\tMessage size mean: 16 B min: 16 B max: 16 B\n"


def command_result(stdout="", return_code=0, stderr="", timed_out=None):
    result = {"return_code": return_code, "stdout": stdout, "stderr": stderr}
    if timed_out is not None:
        result["timed_out"] = timed_out
    return result


def sampled(stdout):
    return command_result(stdout, return_code=124, timed_out=True)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", "file:monitor_test?mode=memory&cache=shared")
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
    monkeypatch.setattr(monitor, "ros2_command", mock)
    return mock


@pytest.mark.parametrize(
    "topic",
    [None, "", "relative", "/", "/bad name", "/a//b", "/a/", "/9bad", "--help", "/a\nb", "/" + "a" * 256],
)
def test_invalid_topic_does_not_call_runner(client, command, topic):
    query = {} if topic is None else {"topic": topic}
    response = client.get("/api/topic-monitor", query_string=query)
    assert response.status_code == 400
    assert "error" in response.get_json()
    command.assert_not_called()


def test_returns_latest_measurements_for_selected_topic(client, command):
    command.side_effect = [
        command_result("sensor_msgs/msg/LaserScan\n"),
        sampled(HZ + "average rate: 12.500\n"),
        sampled("Subscribed to [/robot_2/scan]\n" + BW + "1.25 KB/s from 20 messages\n"),
    ]
    response = client.get("/api/topic-monitor?topic=/robot_2/scan")
    assert response.status_code == 200
    assert response.get_json() == {
        "source": "ros2",
        "topic": "/robot_2/scan",
        "frequency_hz": 12.5,
        "bandwidth_bytes_per_second": 1250.0,
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert command.call_args_list[0].args == (
        "topic", "--include-hidden-topics", "type", "/robot_2/scan"
    )
    assert command.call_args_list[1].args == (
        "topic", "hz", "/robot_2/scan", "--window", "100", "--wall-time"
    )
    assert command.call_args_list[2].args == (
        "topic", "bw", "/robot_2/scan", "--window", "100"
    )
    for call in command.call_args_list[1:]:
        assert call.kwargs == {"timeout_seconds": 5.0, "capture_on_timeout": True}


@pytest.mark.parametrize(
    "value, unit, expected", [(32, "B", 32), (1.25, "KB", 1250), (2.5, "MB", 2500000)]
)
def test_bandwidth_uses_decimal_bytes_per_second(client, command, value, unit, expected):
    command.side_effect = [
        command_result("std_msgs/msg/String\n"),
        sampled(HZ),
        sampled(f"{value} {unit}/s from 8 messages\n"),
    ]
    response = client.get("/api/topic-monitor?topic=/status")
    assert response.status_code == 200
    assert response.get_json()["bandwidth_bytes_per_second"] == expected


def test_incomplete_trailing_lines_are_ignored(client, command):
    command.side_effect = [
        command_result("std_msgs/msg/Float64\n"),
        sampled(HZ + "average rate: 9"),
        sampled(BW + "1.25 MB/s from 2 messages"),
    ]
    response = client.get("/api/topic-monitor?topic=/reading")
    assert response.status_code == 200
    assert response.get_json()["frequency_hz"] == 2.0
    assert response.get_json()["bandwidth_bytes_per_second"] == 32.0


def test_short_command_timeout_limits_both_measurements(app, client, command):
    app.config["ROS2_COMMAND_TIMEOUT"] = 4
    command.side_effect = [command_result("std_msgs/msg/String\n"), sampled(HZ), sampled(BW)]
    assert client.get("/api/topic-monitor?topic=/status").status_code == 200
    assert all(call.kwargs["timeout_seconds"] == 4 for call in command.call_args_list[1:])


@pytest.mark.parametrize(
    "result, status",
    [
        (command_result(), 404),
        (command_result(return_code=1), 404),
        (command_result(return_code=1, stderr="Discovery failed"), 502),
        (command_result("std_msgs/msg/String\nstd_msgs/msg/Float64\n"), 409),
        (command_result("invalid/type\n"), 502),
    ],
)
def test_type_discovery_errors_do_not_start_measurements(client, command, result, status):
    command.return_value = result
    response = client.get("/api/topic-monitor?topic=/status")
    assert response.status_code == status
    assert "error" in response.get_json()
    assert command.call_count == 1


@pytest.mark.parametrize(
    "stage, output, status",
    [
        ("hz", "", 504),
        ("hz", "WARNING: topic is not published yet\n", 504),
        ("hz", "average rate: nan\n", 502),
        ("hz", "average rate: -1.0\n", 502),
        ("hz", "average rate: invalid\n", 502),
        ("bw", "Subscribed to [/status]\n", 504),
        ("bw", "nan B/s from 2 messages\n", 502),
        ("bw", "-1 B/s from 2 messages\n", 502),
        ("bw", "1 KiB/s from 2 messages\n", 502),
    ],
)
def test_missing_or_invalid_statistics_return_errors(client, command, stage, output, status):
    results = [command_result("std_msgs/msg/String\n")]
    if stage == "bw":
        results.append(sampled(HZ))
    results.append(sampled(output))
    command.side_effect = results
    response = client.get("/api/topic-monitor?topic=/status")
    assert response.status_code == status
    assert set(response.get_json()) == {"error"}


@pytest.mark.parametrize("return_code, timed_out", [(1, False), (124, False)])
def test_failed_commands_cannot_supply_measurements(client, command, return_code, timed_out):
    command.side_effect = [
        command_result("std_msgs/msg/String\n"),
        command_result(HZ, return_code=return_code, timed_out=timed_out),
    ]
    assert client.get("/api/topic-monitor?topic=/status").status_code == 502


@pytest.mark.parametrize("stage", ["type", "hz", "bw"])
def test_runner_failures_return_json(client, command, stage):
    results = []
    if stage != "type":
        results.append(command_result("std_msgs/msg/String\n"))
    if stage == "bw":
        results.append(sampled(HZ))
    command.side_effect = results + [Ros2CommandError("Runner unavailable")]
    response = client.get("/api/topic-monitor?topic=/status")
    assert response.status_code == 503
    assert response.get_json() == {"error": "Runner unavailable"}


def test_metrics_use_http_runner_and_refresh_samples(app, client, monkeypatch):
    # Exercise HTTP and timeout handling, simulating only the ROS process.
    rates = iter(["average rate: 1.500\n", "average rate: 3.000\n"])
    commands = []

    def subprocess_run(arguments, **options):
        commands.append(arguments)
        assert options["shell"] is False
        assert options["env"]["PYTHONUNBUFFERED"] == "1"
        if arguments[1:4] == ["topic", "--include-hidden-topics", "type"]:
            assert arguments[4] == "/custom/reading"
            return subprocess.CompletedProcess(arguments, 0, "std_msgs/msg/Float64\n", "")
        assert arguments[3] == "/custom/reading"
        assert options["timeout"] == 5.0
        output = next(rates) if arguments[2] == "hz" else BW
        raise subprocess.TimeoutExpired(arguments, options["timeout"], output=output.encode())

    monkeypatch.setattr("runner.server.subprocess.run", subprocess_run)
    server = ThreadingHTTPServer(("127.0.0.1", 0), CommandHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    app.config["ROS2_RUNNER_ADDRESS"] = "127.0.0.1"
    app.config["ROS2_RUNNER_PORT"] = server.server_port
    try:
        first = client.get("/api/topic-monitor?topic=/custom/reading")
        second = client.get("/api/topic-monitor?topic=/custom/reading")
        assert first.status_code == second.status_code == 200
        assert first.get_json()["frequency_hz"] == 1.5
        assert second.get_json()["frequency_hz"] == 3.0
        assert second.get_json()["bandwidth_bytes_per_second"] == 32.0
        assert len(commands) == 6
        assert not any("echo" in arguments for arguments in commands)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
