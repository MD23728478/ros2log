APP_ENV = "development"
PERSIST_DATABASE = True
SERVER_ADDRESS = "0.0.0.0"
SERVER_PORT = 5000
ROS2_RUNNER_PORT = 8765
ROS2_COMMAND_TIMEOUT = 30
RECORDING_TIMEOUT_SECONDS = 3600
TOPIC_MONITOR_WINDOW = {"default": 100, "min": 2, "max": 10000}

if APP_ENV not in {"development", "production"}:
    raise ValueError("APP_ENV must be 'development' or 'production'")

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
