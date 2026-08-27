#!/bin/sh
set -eu

app_env=$(python -c "import config; print(config.APP_ENV)")
server_address=$(python -c "import config; print(config.SERVER_ADDRESS)")
server_port=$(python -c "import config; print(config.SERVER_PORT)")

if [ "$app_env" = "production" ]; then
    echo "Starting production server at $server_address:$server_port"
exec gunicorn \
    --bind "$server_address:$server_port" \
    --worker-class gthread \
    --workers "${gunicorn_workers:-2}" \
    --threads "${gunicorn_threads:-4}" \
    --timeout "${gunicorn_timeout:-120}" \
    --graceful-timeout "${gunicorn_graceful_timeout:-30}" \
    --keep-alive 5 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --access-logfile - \
    --error-logfile - \
    --capture-output \
    "backend.app:create_app()"
fi

echo "Starting development server at $server_address:$server_port"
exec flask --app "backend.app:create_app" run \
    --host="$server_address" \
    --port="$server_port" \
    --debug
