import math
from pathlib import Path


# Change these settings in this file alone.
APP_ENV = "development"  # Selects development or production runner connection.
PERSIST_DATABASE = True  # Stores SQLite on disk when true; uses memory when false.
ROS2_RUNNER_PORT = 8765  # Shared by the app client and ROS 2 runner server.
ROS2_COMMAND_TIMEOUT = 30  # Maximum seconds for a synchronous ROS 2 command.
RECORDING_TIMEOUT_SECONDS = 86400  # Maximum seconds for a bag recording.
TOPIC_MONITOR_WINDOW = {"default": 100, "min": 2, "max": 10000}  # Message count limits.
PERFORMANCE_POLL_INTERVAL_SECONDS = 300  # Seconds between browser metric polls.

# These settings depend on Docker, host paths, or other settings.
STORAGE_PATH = Path("/storage")  # Container path; host mount is set in compose.yaml, and docker/Dockerfile creates it.
SERVER_ADDRESS = "0.0.0.0"  # Must listen on all container interfaces for Compose port forwarding.
SERVER_PORT = 5000  # Also set in compose.yaml ports and docker/Dockerfile EXPOSE.
DEBUG = APP_ENV == "development"  # Follows the selected application environment.
LOGGING_ENABLED = APP_ENV == "development"  # Follows the selected application environment.
LOG_LEVEL = "DEBUG" if LOGGING_ENABLED else "WARNING"  # Follows logging enablement.
ROS2_RUNNER_ADDRESS = (  # Uses the Compose service name or the production host alias.
    "ros2" if APP_ENV == "development" else "host.docker.internal"
)
DATABASE = (  # Uses STORAGE_PATH for persistent SQLite; otherwise uses shared memory.
    str(STORAGE_PATH / "app.db")
    if PERSIST_DATABASE
    else "file:ros2log?mode=memory&cache=shared"
)

if APP_ENV not in {"development", "production"}:
    raise ValueError("APP_ENV must be 'development' or 'production'")

if (
    not isinstance(PERFORMANCE_POLL_INTERVAL_SECONDS, (int, float))
    or isinstance(PERFORMANCE_POLL_INTERVAL_SECONDS, bool)
    or not math.isfinite(PERFORMANCE_POLL_INTERVAL_SECONDS)
    or PERFORMANCE_POLL_INTERVAL_SECONDS <= 0
):
    raise ValueError("PERFORMANCE_POLL_INTERVAL_SECONDS must be greater than zero")
