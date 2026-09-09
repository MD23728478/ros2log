import json
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
) -> dict[str, int | str]:
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
        or timeout <= 0
    ):
        raise Ros2CommandError("ROS 2 command timeout must be greater than zero")

    address = current_app.config["ROS2_RUNNER_ADDRESS"]
    port = current_app.config["ROS2_RUNNER_PORT"]
    request = Request(
        f"http://{address}:{port}/command",
        data=json.dumps(
            {"arguments": arguments, "timeout_seconds": timeout}
        ).encode("utf-8"),
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

    if (
        not isinstance(result, dict)
        or type(result.get("return_code")) is not int
        or not isinstance(result.get("stdout"), str)
        or not isinstance(result.get("stderr"), str)
    ):
        raise Ros2CommandError("ROS 2 runner returned an invalid response")

    return result
