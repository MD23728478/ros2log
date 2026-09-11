import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app


class Ros2CommandError(Exception):
    pass


class Ros2BackgroundCommandError(Ros2CommandError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _valid_arguments(arguments) -> bool:
    return bool(arguments) and all(
        isinstance(argument, str) and argument for argument in arguments
    )


def _valid_timeout(timeout) -> bool:
    return (
        isinstance(timeout, (int, float))
        and not isinstance(timeout, bool)
        and math.isfinite(timeout)
        and timeout > 0
    )


def ros2_runner_is_healthy() -> bool:
    address = current_app.config["ROS2_RUNNER_ADDRESS"]
    port = current_app.config["ROS2_RUNNER_PORT"]

    try:
        with urlopen(f"http://{address}:{port}/health", timeout=2) as response:
            result = json.load(response)
    except (OSError, URLError, json.JSONDecodeError):
        return False

    return result == {"status": "ok"}


def ros2_command(
    *arguments: str,
    timeout_seconds: float | None = None,
    capture_on_timeout: bool = False,
) -> dict[str, int | str | bool]:
    if not _valid_arguments(arguments):
        raise Ros2CommandError("ROS 2 command arguments must be non-empty strings")

    timeout = (
        current_app.config["ROS2_COMMAND_TIMEOUT"]
        if timeout_seconds is None
        else timeout_seconds
    )
    if not _valid_timeout(timeout):
        raise Ros2CommandError("ROS 2 command timeout must be greater than zero")

    if not isinstance(capture_on_timeout, bool):
        raise Ros2CommandError("capture_on_timeout must be a boolean")

    payload = {"arguments": arguments, "timeout_seconds": timeout}
    if capture_on_timeout:
        payload["capture_on_timeout"] = True

    address = current_app.config["ROS2_RUNNER_ADDRESS"]
    port = current_app.config["ROS2_RUNNER_PORT"]
    request = Request(
        f"http://{address}:{port}/command",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout + 1) as response:
            result = json.load(response)
    except HTTPError as error:
        try:
            message = json.load(error).get("error", str(error))
        except (AttributeError, json.JSONDecodeError):
            message = str(error)
        raise Ros2CommandError(message) from error
    except (OSError, URLError) as error:
        raise Ros2CommandError(f"ROS 2 runner is unavailable: {error}") from error
    except json.JSONDecodeError as error:
        raise Ros2CommandError("ROS 2 runner returned invalid JSON") from error

    if (
        not isinstance(result, dict)
        or type(result.get("return_code")) is not int
        or not isinstance(result.get("stdout"), str)
        or not isinstance(result.get("stderr"), str)
        or (
            capture_on_timeout
            and type(result.get("timed_out")) is not bool
        )
    ):
        raise Ros2CommandError("ROS 2 runner returned an invalid response")

    return result


def ros2_background_command_start(
    *arguments: str,
    timeout_seconds: float,
) -> dict[str, int | str | bool | None]:
    if not _valid_arguments(arguments):
        raise Ros2BackgroundCommandError(
            "ROS 2 command arguments must be non-empty strings"
        )
    if not _valid_timeout(timeout_seconds):
        raise Ros2BackgroundCommandError(
            "ROS 2 background command timeout must be greater than zero"
        )

    result = _background_command_request(
        "/background-command",
        method="POST",
        payload={"arguments": arguments, "timeout_seconds": timeout_seconds},
    )
    return _validate_background_command_result(result)


def ros2_background_command_status() -> dict[str, int | str | bool | None]:
    result = _background_command_request("/background-command")
    return _validate_background_command_result(result)


def ros2_background_command_stop() -> dict[str, int | str | bool | None]:
    result = _background_command_request(
        "/background-command/stop",
        method="POST",
        request_timeout=BACKGROUND_STOP_REQUEST_TIMEOUT,
    )
    return _validate_background_command_result(result)


BACKGROUND_REQUEST_TIMEOUT = 2
BACKGROUND_STOP_REQUEST_TIMEOUT = 32


def _background_command_request(
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    request_timeout: float = BACKGROUND_REQUEST_TIMEOUT,
):
    address = current_app.config["ROS2_RUNNER_ADDRESS"]
    port = current_app.config["ROS2_RUNNER_PORT"]
    request_data = None
    headers = {}
    if payload is not None:
        request_data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        f"http://{address}:{port}{path}",
        data=request_data,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=request_timeout) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            message = json.load(error).get("error", str(error))
        except (AttributeError, json.JSONDecodeError):
            message = str(error)
        raise Ros2BackgroundCommandError(message, error.code) from error
    except (OSError, URLError) as error:
        raise Ros2BackgroundCommandError(
            f"ROS 2 runner is unavailable: {error}"
        ) from error
    except json.JSONDecodeError as error:
        raise Ros2BackgroundCommandError(
            "ROS 2 runner returned invalid JSON"
        ) from error


def _validate_background_command_result(
    result,
) -> dict[str, int | str | bool | None]:
    if not isinstance(result, dict):
        raise Ros2BackgroundCommandError(
            "ROS 2 runner returned an invalid background command response"
        )

    return_code = result.get("return_code")
    state = result.get("state")
    termination_reason = result.get("termination_reason")
    valid = (
        isinstance(state, str)
        and state in {"running", "stopping", "finished"}
        and (return_code is None or type(return_code) is int)
        and isinstance(result.get("stdout"), str)
        and isinstance(result.get("stderr"), str)
        and type(result.get("stdout_truncated")) is bool
        and type(result.get("stderr_truncated")) is bool
        and (
            termination_reason is None
            or (
                isinstance(termination_reason, str)
                and termination_reason in {"manual", "timeout"}
            )
        )
        and type(result.get("forced")) is bool
    )
    if not valid:
        raise Ros2BackgroundCommandError(
            "ROS 2 runner returned an invalid background command response"
        )
    return result
