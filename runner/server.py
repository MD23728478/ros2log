import argparse
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config


def run_command(arguments: list[str], timeout_seconds: float) -> dict[str, int | str]:
    completed = subprocess.run(
        ["ros2", *arguments],
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return {
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


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
            if (
                not isinstance(arguments, list)
                or not arguments
                or not all(
                    isinstance(argument, str) and argument for argument in arguments
                )
                or not isinstance(timeout_seconds, (int, float))
                or isinstance(timeout_seconds, bool)
                or timeout_seconds <= 0
            ):
                raise ValueError
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self.send_json(400, {"error": "Invalid command request"})
            return

        try:
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
