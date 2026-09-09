from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

from backend.app import create_app
from runner.client import ros2_command
from runner.server import CommandHandler


def test_ros2_command_over_http():
    server = ThreadingHTTPServer(("127.0.0.1", 0), CommandHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        app = create_app()
        app.config["ROS2_RUNNER_ADDRESS"] = "127.0.0.1"
        app.config["ROS2_RUNNER_PORT"] = server.server_port

        result = {"return_code": 0, "stdout": "", "stderr": ""}
        with patch("runner.server.run_command", return_value=result):
            with app.app_context():
                assert ros2_command("node", "list")["return_code"] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
