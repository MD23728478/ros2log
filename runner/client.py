import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app


class Ros2CommandError(Exception):
    pass


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
