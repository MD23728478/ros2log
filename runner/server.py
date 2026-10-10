import argparse
import json
import math
import os
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import config
from runner.metrics import MetricsError, collect_metrics


BACKGROUND_OUTPUT_LIMIT = 64 * 1024
BACKGROUND_STOP_GRACE_SECONDS = 30


def host_storage_path() -> Path:
    return Path(config.__file__).resolve().parent / config.RUNNER_STORAGE_PATH


class OutputTail:
    def __init__(self, limit: int = BACKGROUND_OUTPUT_LIMIT) -> None:
        self.limit = limit
        self.value = ""
        self.truncated = False

    def append(self, value: str) -> None:
        self.value += value
        if len(self.value) > self.limit:
            self.value = self.value[-self.limit :]
            self.truncated = True


class BackgroundCommand:
    def __init__(
        self,
        process: subprocess.Popen,
        timeout_seconds: float,
    ) -> None:
        self.process = process
        self.state = "running"
        self.return_code = None
        self.termination_reason = None
        self.forced = False
        self.stdout = OutputTail()
        self.stderr = OutputTail()
        self.lock = threading.RLock()

        self.stdout_thread = threading.Thread(
            target=self._read_stream, args=(process.stdout, self.stdout), daemon=True
        )
        self.stderr_thread = threading.Thread(
            target=self._read_stream, args=(process.stderr, self.stderr), daemon=True
        )
        self.wait_thread = threading.Thread(target=self._wait, daemon=True)
        self.deadline_timer = threading.Timer(timeout_seconds, self.stop, args=("timeout",))
        self.deadline_timer.daemon = True

        self.stdout_thread.start()
        self.stderr_thread.start()
        self.wait_thread.start()
        self.deadline_timer.start()

    def _read_stream(self, stream, output: OutputTail) -> None:
        if stream is None:
            return
        try:
            while chunk := stream.readline():
                with self.lock:
                    output.append(chunk)
        finally:
            stream.close()

    def _wait(self) -> None:
        return_code = self.process.wait()
        self.stdout_thread.join()
        self.stderr_thread.join()
        with self.lock:
            self.return_code = return_code
            self.state = "finished"
            self.deadline_timer.cancel()
        print(f"Runner background command finished (exit {return_code})", flush=True)

    def stop(self, reason: str = "manual") -> None:
        with self.lock:
            if self.state == "finished":
                return
            should_signal = self.state == "running"
            if should_signal:
                self.termination_reason = reason
                self.state = "stopping"

        if not should_signal:
            self.wait_thread.join()
            return

        print(f"Runner background command stopping ({reason})", flush=True)
        try:
            os.killpg(self.process.pid, signal.SIGINT)
        except ProcessLookupError:
            self.wait_thread.join()
            return

        try:
            self.process.wait(timeout=BACKGROUND_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            with self.lock:
                self.forced = True
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()

        self.wait_thread.join()

    def result(self) -> dict[str, int | str | bool | None]:
        with self.lock:
            return {
                "state": self.state,
                "return_code": self.return_code,
                "stdout": self.stdout.value,
                "stderr": self.stderr.value,
                "stdout_truncated": self.stdout.truncated,
                "stderr_truncated": self.stderr.truncated,
                "termination_reason": self.termination_reason,
                "forced": self.forced,
            }


class BackgroundCommandSlot:
    def __init__(self) -> None:
        self.command: BackgroundCommand | None = None
        self.lock = threading.Lock()

    def start(self, arguments: list[str], timeout_seconds: float) -> dict | None:
        with self.lock:
            if (
                self.command is not None
                and self.command.result()["state"] != "finished"
            ):
                return None
            if config.APP_ENV == "production" and (
                arguments[:2] == ["bag", "record"]
                or arguments[:3] == ["run", "rosbag2_transport", "recorder"]
            ):
                arguments = arguments.copy()
                for index, value in enumerate(arguments):
                    if index and arguments[index - 1] in {"--output", "--params-file"}:
                        parameter = ""
                        path = value
                    elif (
                        index and arguments[index - 1] in {"-p", "--param"}
                        and value.startswith("storage.uri:=")
                    ):
                        parameter = "storage.uri:="
                        path = value[len(parameter):]
                        try:
                            path = json.loads(path)
                        except json.JSONDecodeError:
                            pass
                        if not isinstance(path, str):
                            continue
                    else:
                        continue
                    try:
                        relative = Path(path).relative_to(config.STORAGE_PATH)
                    except ValueError:
                        continue
                    host_storage_path().mkdir(parents=True, exist_ok=True)
                    host_path = str(host_storage_path() / relative)
                    arguments[index] = parameter + json.dumps(host_path, ensure_ascii=False) if parameter else host_path
            print(f"Runner background command starting: {arguments}", flush=True)
            process = subprocess.Popen(
                [config.ROS2_EXECUTABLE_PATH or "ros2", *arguments],
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            self.command = BackgroundCommand(process, timeout_seconds)
            return self.command.result()

    def status(self) -> dict | None:
        with self.lock:
            command = self.command
        return command.result() if command is not None else None

    def stop(self) -> dict | None:
        with self.lock:
            command = self.command
        if command is None:
            return None
        command.stop()
        return command.result()

    def shutdown(self) -> None:
        with self.lock:
            command = self.command
        if command is not None:
            command.stop()


def valid_arguments(arguments) -> bool:
    return (
        isinstance(arguments, list)
        and bool(arguments)
        and all(isinstance(argument, str) and argument for argument in arguments)
    )


def valid_timeout(timeout) -> bool:
    return (
        isinstance(timeout, (int, float))
        and not isinstance(timeout, bool)
        and math.isfinite(timeout)
        and timeout > 0
    )


def run_command(
    arguments: list[str],
    timeout_seconds: float,
    *,
    capture_on_timeout: bool = False,
) -> dict[str, int | str | bool]:
    print(f"Runner command: {arguments}", flush=True)
    try:
        completed = subprocess.run(
            [config.ROS2_EXECUTABLE_PATH or "ros2", *arguments],
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

        if self.path == "/metrics":
            try:
                if config.APP_ENV == "production":
                    storage_path = host_storage_path()
                    storage_path.mkdir(parents=True, exist_ok=True)
                    result = collect_metrics(storage_path=storage_path)
                else:
                    result = collect_metrics()
            except OSError as error:
                self.send_json(500, {"error": f"Could not access runner storage: {error}"})
                return
            except MetricsError as error:
                self.send_json(500, {"error": str(error)})
                return
            self.send_json(200, result)
            return

        if self.path == "/background-command":
            result = self.server.background_command.status()
            if result is None:
                self.send_json(404, {"error": "Background command not found"})
                return
            self.send_json(200, result)
            return

        self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/background-command":
            self.start_background_command()
            return

        if self.path == "/background-command/stop":
            result = self.server.background_command.stop()
            if result is None:
                self.send_json(404, {"error": "Background command not found"})
                return
            self.send_json(200, result)
            return

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
                not valid_arguments(arguments)
                or not valid_timeout(timeout_seconds)
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

    def start_background_command(self) -> None:
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "Content-Type must be application/json"})
            return

        try:
            data = self.read_json()
            arguments = data["arguments"]
            timeout_seconds = data["timeout_seconds"]
            if not valid_arguments(arguments) or not valid_timeout(timeout_seconds):
                raise ValueError
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self.send_json(400, {"error": "Invalid background command request"})
            return

        try:
            result = self.server.background_command.start(arguments, timeout_seconds)
        except OSError as error:
            self.send_json(500, {"error": f"Could not run ROS 2 command: {error}"})
            return
        if result is None:
            self.send_json(409, {"error": "Background command is already active"})
            return
        self.send_json(201, result)

    def read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(content_length))

    def send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *arguments) -> None:
        print(f"Runner request {self.client_address[0]}: {format % arguments}", flush=True)


class RunnerServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class=CommandHandler) -> None:
        super().__init__(server_address, handler_class)
        self.background_command = BackgroundCommandSlot()

    def server_close(self) -> None:
        self.background_command.shutdown()
        super().server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ROS 2 commands for ros2log")
    parser.add_argument("--address", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=config.ROS2_RUNNER_PORT)
    arguments = parser.parse_args()

    server = RunnerServer((arguments.address, arguments.port))
    print(f"ROS 2 command runner listening on {arguments.address}:{arguments.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
