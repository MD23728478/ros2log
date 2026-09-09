#!/bin/sh
set -eu

python3 /app/docker/ros2/test_topics.py &
publisher_pid=$!

cleanup() {
    kill "$publisher_pid" 2>/dev/null || true
    wait "$publisher_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM
python3 -m runner.server
