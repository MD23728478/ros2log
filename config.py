APP_ENV = "development"
PERSIST_DATABASE = True
SERVER_ADDRESS = "0.0.0.0"
SERVER_PORT = 5000

if APP_ENV not in {"development", "production"}:
    raise ValueError("APP_ENV must be 'development' or 'production'")

DEBUG = APP_ENV == "development"
LOGGING_ENABLED = APP_ENV == "development"
LOG_LEVEL = "DEBUG" if LOGGING_ENABLED else "WARNING"
DATABASE = (
    "/storage/app.db"
    if PERSIST_DATABASE
    else "file:ros2log?mode=memory&cache=shared"
)
