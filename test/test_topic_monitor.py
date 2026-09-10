import json
from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import Mock

import pytest

import config
from backend.api import topic_monitor as monitor
from backend.app import create_app
from runner.client import Ros2CommandError
from runner.server import CommandHandler


def command_result(stdout="", return_code=0, stderr=""):
    return {"return_code": return_code, "stdout": stdout, "stderr": stderr}


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
    [
        None, "", "relative", "/", "/bad name", "/a//b", "/a/",
        "/9bad", "--help", "/a\nb", "/" + "a" * 256,
    ],
)
def test_invalid_topic_does_not_call_runner(client, command, topic):
    query = {} if topic is None else {"topic": topic}
    response = client.get("/api/topic-monitor", query_string=query)
    assert response.status_code == 400
    assert "error" in response.get_json()
    command.assert_not_called()


@pytest.mark.parametrize(
    "message_type, output, expected",
    [
        ("std_msgs/msg/Float64", "data: 18.6\n---\n", {"data": 18.6}),
        ("std_msgs/msg/String", "data: 'off'\n---\n", {"data": "off"}),
        (
            "example_msgs/msg/Nested",
            "pose:\n  x: 1.5\n  y: -2.0\nactive: true\n---\n",
            {"pose": {"x": 1.5, "y": -2.0}, "active": True},
        ),
        ("std_msgs/msg/Empty", "{}\n---\n", {}),
        (
            "std_msgs/msg/Float64MultiArray",
            "data: [.nan, .inf, -.inf]\n---\n",
            {"data": ["nan", "inf", "-inf"]},
        ),
        ("std_msgs/msg/ByteMultiArray", "data: !!binary AQID\n---\n", {"data": [1, 2, 3]}),
    ],
)
def test_reads_selected_topic_and_preserves_message(
    client, command, message_type, output, expected
):
    command.side_effect = [command_result(message_type + "\n"), command_result(output)]
    response = client.get("/api/topic-monitor", query_string={"topic": "/robot_2/sensor"})
    assert response.status_code == 200
    assert response.get_json() == {
        "source": "ros2",
        "topic": "/robot_2/sensor",
        "message_type": message_type,
        "latest_message": expected,
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert command.call_args_list[0].args == (
        "topic", "--include-hidden-topics", "type", "/robot_2/sensor"
    )
    echo_arguments = command.call_args_list[1].args
    assert echo_arguments[:4] == ("topic", "echo", "/robot_2/sensor", message_type)
    assert "--once" in echo_arguments
    assert "--full-length" in echo_arguments
    assert echo_arguments[echo_arguments.index("--timeout") + 1] == "5.0"


def test_short_command_timeout_reduces_message_wait(app, client, command):
    app.config["ROS2_COMMAND_TIMEOUT"] = 4
    command.side_effect = [
        command_result("std_msgs/msg/String\n"),
        command_result("data: hello\n---\n"),
    ]
    assert client.get("/api/topic-monitor?topic=/status").status_code == 200
    arguments = command.call_args.args
    assert arguments[arguments.index("--timeout") + 1] == "2.0"


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
def test_type_discovery_errors_do_not_subscribe(client, command, result, status):
    command.return_value = result
    response = client.get("/api/topic-monitor?topic=/status")
    assert response.status_code == status
    assert "error" in response.get_json()
    assert "latest_message" not in response.get_json()
    assert command.call_count == 1


@pytest.mark.parametrize(
    "result, status",
    [
        (command_result(), 504),
        (command_result(return_code=1, stderr="Subscription failed"), 502),
        (command_result("data: [broken\n---\n"), 502),
        (command_result("data: 1\n---\ndata: 2\n---\n"), 502),
        (command_result("not a message\n---\n"), 502),
        (command_result("---\n"), 502),
        (command_result("data: !!python/object:example {}\n---\n"), 502),
    ],
)
def test_message_errors_never_return_sample_data(client, command, result, status):
    command.side_effect = [command_result("std_msgs/msg/String\n"), result]
    response = client.get("/api/topic-monitor?topic=/status")
    assert response.status_code == status
    assert "error" in response.get_json()
    assert "latest_message" not in response.get_json()


@pytest.mark.parametrize("stage", ["type", "echo"])
def test_runner_failures_return_json(client, command, stage):
    failure = Ros2CommandError("Runner unavailable")
    command.side_effect = (
        failure if stage == "type"
        else [command_result("std_msgs/msg/String\n"), failure]
    )
    response = client.get("/api/topic-monitor?topic=/status")
    assert response.status_code == 503
    assert response.get_json() == {"error": "Runner unavailable"}


def test_malformed_runner_json_returns_json_error(client, command):
    command.side_effect = json.JSONDecodeError("Invalid runner JSON", "invalid", 0)
    response = client.get("/api/topic-monitor?topic=/status")
    assert response.status_code == 502
    assert "error" in response.get_json()


def test_monitor_uses_http_runner_and_fetches_new_data(app, client, monkeypatch):
    # Exercise the route and real HTTP client/server together. Only the ROS
    # process is replaced, so this test does not require a ROS installation.
    readings = iter(["data: 12.5\n---\n", "data: 34.8\n---\n"])
    calls = []

    def run_command(arguments, timeout_seconds):
        calls.append(arguments)
        assert timeout_seconds == config.ROS2_COMMAND_TIMEOUT
        if arguments[:3] == ["topic", "--include-hidden-topics", "type"]:
            assert arguments[3] == "/custom/reading"
            return command_result("std_msgs/msg/Float64\n")
        assert arguments[:3] == ["topic", "echo", "/custom/reading"]
        return command_result(next(readings))

    monkeypatch.setattr("runner.server.run_command", run_command)
    server = ThreadingHTTPServer(("127.0.0.1", 0), CommandHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    app.config["ROS2_RUNNER_ADDRESS"] = "127.0.0.1"
    app.config["ROS2_RUNNER_PORT"] = server.server_port
    try:
        first = client.get("/api/topic-monitor?topic=/custom/reading")
        second = client.get("/api/topic-monitor?topic=/custom/reading")
        assert first.status_code == second.status_code == 200
        assert first.get_json()["latest_message"] == {"data": 12.5}
        assert second.get_json()["latest_message"] == {"data": 34.8}
        assert len(calls) == 4
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
