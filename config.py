import math


APP_ENV = "development"
PERSIST_DATABASE = True
SERVER_ADDRESS = "0.0.0.0"
SERVER_PORT = 5000
ROS2_RUNNER_PORT = 8765
ROS2_COMMAND_TIMEOUT = 30
RECORDING_TIMEOUT_SECONDS = 86400
TOPIC_MONITOR_WINDOW = {"default": 100, "min": 2, "max": 10000}
PERFORMANCE_POLL_INTERVAL_SECONDS = 300

if APP_ENV not in {"development", "production"}:
    raise ValueError("APP_ENV must be 'development' or 'production'")

if (
    not isinstance(PERFORMANCE_POLL_INTERVAL_SECONDS, (int, float))
    or isinstance(PERFORMANCE_POLL_INTERVAL_SECONDS, bool)
    or not math.isfinite(PERFORMANCE_POLL_INTERVAL_SECONDS)
    or PERFORMANCE_POLL_INTERVAL_SECONDS <= 0
):
    raise ValueError("PERFORMANCE_POLL_INTERVAL_SECONDS must be greater than zero")

DEBUG = APP_ENV == "development"
LOGGING_ENABLED = APP_ENV == "development"
LOG_LEVEL = "DEBUG" if LOGGING_ENABLED else "WARNING"
ROS2_RUNNER_ADDRESS = (
    "ros2" if APP_ENV == "development" else "host.docker.internal"
)
DATABASE = (
    "/storage/app.db"
    if PERSIST_DATABASE
    else "file:ros2log?mode=memory&cache=shared"
)
