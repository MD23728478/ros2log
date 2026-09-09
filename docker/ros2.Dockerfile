FROM ros:jazzy-ros-base

WORKDIR /app

COPY config.py ./config.py
COPY backend/__init__.py ./backend/__init__.py
COPY runner ./runner
COPY docker/ros2 ./docker/ros2

RUN chmod 0555 /app/docker/ros2/start.sh

CMD ["/app/docker/ros2/start.sh"]
