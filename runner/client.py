import json
import math
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app


class Ros2CommandError(Exception):
    pass


class Ros2BackgroundCommandError(Ros2CommandError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
    if not arguments or not all(
        isinstance(argument, str) and argument for argument in arguments
    ):
        raise Ros2CommandError("ROS 2 command arguments must be non-empty strings")

    timeout = (
        current_app.config["ROS2_COMMAND_TIMEOUT"]
        if timeout_seconds is None
        else timeout_seconds
    )
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
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
    if not arguments or not all(
        isinstance(argument, str) and argument for argument in arguments
    ):
        raise Ros2BackgroundCommandError(
            "ROS 2 command arguments must be non-empty strings"
        )
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise Ros2BackgroundCommandError(
            "ROS 2 background command timeout must be greater than zero"
        )

    result = _background_command_request(
        "/background-command",
        method="POST",
        payload={"arguments": arguments, "timeout_seconds": timeout_seconds},
    )
    return _validate_background_command_result(result)


def ros2_background_command_status(
    command_id: str,
) -> dict[str, int | str | bool | None]:
    command_id = _validate_background_command_id(command_id)
    result = _background_command_request(f"/background-command/{command_id}")
    return _validate_background_command_result(result, command_id)


def ros2_background_command_stop(
    command_id: str,
) -> dict[str, int | str | bool | None]:
    command_id = _validate_background_command_id(command_id)
    result = _background_command_request(
        f"/background-command/{command_id}/stop",
        method="POST",
        request_timeout=BACKGROUND_STOP_REQUEST_TIMEOUT,
    )
    return _validate_background_command_result(result, command_id)


def ros2_background_command_forget(command_id: str) -> None:
    command_id = _validate_background_command_id(command_id)
    _background_command_request(
        f"/background-command/{command_id}",
        method="DELETE",
        expect_json=False,
    )


BACKGROUND_REQUEST_TIMEOUT = 2
BACKGROUND_STOP_REQUEST_TIMEOUT = 32


def _background_command_request(
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    request_timeout: float = BACKGROUND_REQUEST_TIMEOUT,
    expect_json: bool = True,
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
            if not expect_json:
                return None
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


def _validate_background_command_id(command_id: str) -> str:
    try:
        normalized = str(uuid.UUID(command_id))
    except (AttributeError, TypeError, ValueError) as error:
        raise Ros2BackgroundCommandError(
            "ROS 2 background command ID is invalid"
        ) from error
    if command_id != normalized:
        raise Ros2BackgroundCommandError("ROS 2 background command ID is invalid")
    return normalized


def _validate_background_command_result(
    result,
    expected_command_id: str | None = None,
) -> dict[str, int | str | bool | None]:
    if not isinstance(result, dict):
        raise Ros2BackgroundCommandError(
            "ROS 2 runner returned an invalid background command response"
        )

    command_id = result.get("command_id")
    return_code = result.get("return_code")
    state = result.get("state")
    termination_reason = result.get("termination_reason")
    valid = (
        isinstance(command_id, str)
        and (expected_command_id is None or command_id == expected_command_id)
        and isinstance(state, str)
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
    if valid:
        try:
            valid = str(uuid.UUID(command_id)) == command_id
        except ValueError:
            valid = False
    if not valid:
        raise Ros2BackgroundCommandError(
            "ROS 2 runner returned an invalid background command response"
        )
    return result
