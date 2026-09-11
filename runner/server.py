import argparse
import json
import math
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config


def run_command(
    arguments: list[str],
    timeout_seconds: float,
    *,
    capture_on_timeout: bool = False,
) -> dict[str, int | str | bool]:
    try:
        completed = subprocess.run(
            ["ros2", *arguments],
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            # The Python ROS CLI must flush measurements before it is stopped.
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired as error:
        if not capture_on_timeout:
            raise
        # subprocess.run has already killed and waited for the command here.
        # TimeoutExpired may contain bytes even though text=True was requested.
        def text_output(output):
            if isinstance(output, bytes):
                return output.decode("utf-8", errors="replace")
            return output or ""

        return {
            "return_code": 124,
            "stdout": text_output(error.stdout),
            "stderr": text_output(error.stderr),
            "timed_out": True,
        }

    result = {
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if capture_on_timeout:
        result["timed_out"] = False
    return result


class CommandHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
            return

        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/command":
            self.send_error(404)
            return

        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "Content-Type must be application/json"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(content_length))
            arguments = data["arguments"]
            timeout_seconds = data.get(
                "timeout_seconds", config.ROS2_COMMAND_TIMEOUT
            )
            capture_on_timeout = data.get("capture_on_timeout", False)
            if (
                not isinstance(arguments, list)
                or not arguments
                or not all(
                    isinstance(argument, str) and argument for argument in arguments
                )
                or not isinstance(timeout_seconds, (int, float))
                or isinstance(timeout_seconds, bool)
                or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0
                or not isinstance(capture_on_timeout, bool)
            ):
                raise ValueError
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self.send_json(400, {"error": "Invalid command request"})
            return

        try:
            if capture_on_timeout:
                result = run_command(
                    arguments, timeout_seconds, capture_on_timeout=True
                )
            else:
                result = run_command(arguments, timeout_seconds)
        except subprocess.TimeoutExpired:
            self.send_json(504, {"error": "ROS 2 command timed out"})
            return
        except OSError as error:
            self.send_json(500, {"error": f"Could not run ROS 2 command: {error}"})
            return

        self.send_json(200, result)

    def send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *arguments) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ROS 2 commands for ros2log")
    parser.add_argument("--address", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=config.ROS2_RUNNER_PORT)
    arguments = parser.parse_args()

    server = ThreadingHTTPServer(
        (arguments.address, arguments.port), CommandHandler
    )
    print(f"ROS 2 command runner listening on {arguments.address}:{arguments.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
