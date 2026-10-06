# ros2log

## Architecture

The Flask application runs in Docker and sends time-limited ROS 2 commands to a
small command runner over HTTP. During development the runner and random test
topics run in a Jazzy container. In production the runner executes directly on
the ROS 2 host. The runner also supports one background command for operations
such as recording a ROS bag. The dashboard lists topics and controls recordings;
the recordings page provides saved bag information and parsed metadata.

```mermaid
flowchart LR
    User[User] -->|HTTP| App

    subgraph Docker
        App[Gunicorn / Flask]
        DB[(Database)]
        Client[Runner Client]

        App --> DB
        App --> Client
    end

    subgraph Host
        Runner[Runner Server]
        ROS[ROS 2]
    end

    Client -->|HTTP| Runner
    Runner --> ROS
```

See [DOCUMENTATION.md](DOCUMENTATION.md) for the project structure and coding
guide.

## Configuration

Edit settings directly in `config.py`:

- `APP_ENV`: `"development"` or `"production"`.
- `ROS2_COMMAND_TIMEOUT`: maximum duration of a finite ROS 2 command.
- `PERFORMANCE_POLL_INTERVAL_SECONDS`: browser performance refresh interval;
  defaults to 300 seconds.
- `RECORDING_TIMEOUT_SECONDS`: maximum duration of a recording.
- `TOPIC_MONITOR_WINDOW`: default and allowed message-count window for topic measurements.
- `STORAGE_PATH`: absolute path to shared storage as seen by the Flask app and
  ROS 2 runner; defaults to `/storage`. Recordings and `app.db` live under it.

The host path and container path are separate. In `compose.yaml`, the shared
volume maps `./storage` (relative to the Compose project directory) to
`/storage` in both development containers. To move only the host files, change
the host side of `x-storage-volume`; `STORAGE_PATH` stays `/storage`. To change
the path seen inside the containers, change `STORAGE_PATH` in `config.py` and
the container side of `x-storage-volume` to the same absolute path. Also update
the directory created in `docker/Dockerfile`. Rebuild both images after editing
`config.py`, since each image copies it at build time.

In production the ROS 2 runner starts on the host, so its `STORAGE_PATH` must
refer to the same files at the same absolute path that the app sees in its
container. Mount or link the host directory accordingly. Existing recording
paths are saved as absolute paths in SQLite; moving the container path also
requires moving the data and updating those rows, or retaining the old path as
a link. Changing `STORAGE_PATH` also changes the default persistent database
location (`<STORAGE_PATH>/app.db`). Keep the old database when moving storage.

The ignore rules in `.gitignore` and `.dockerignore` refer to the default host
`storage` folder. Update them if you move host storage within the project.


## Development

Start the application, Jazzy command runner, and sample ROS 2 topics:

```bash
docker compose --profile development up --build
```

Open <http://localhost:5000>.

Check runner connectivity at <http://localhost:5000/api/ros2/health>.

## Quick start

1. Refresh the Topics list and select the ROS 2 topics you want to use.
2. In Recording, optionally enter a prefix, then start and stop a bag recording.
    With the development Compose setup, recordings are saved under `./storage`
    on the host, mounted as `/storage` in the containers.
3. On the Recordings page, view a recording's metadata or rename and delete it.
4. In Topic Monitor, choose one of the selected topics and measure its message
    frequency (Hz) and bandwidth (B/s). The monitor displays measurements rather
    than graphs.

## Production

Set `APP_ENV = "production"` in `config.py`. On the host, open a terminal where
ROS2 and any required workspace are configured, then start the runner:

```bash
python3 -m runner.server
```

In another terminal, start the Flask application:

```bash
docker compose up --build
```

The runner and Flask application must see the same physical storage at
the configured `STORAGE_PATH` before using background commands to create bag files. The
development Compose profile mounts `./storage` into both containers. See
[DOCUMENTATION.md](DOCUMENTATION.md) for the background command protocol.

## Tests

Run the test suite in the application container:

```bash
docker compose run --build --rm app pytest
```

Run status polling tests with Node.js:

```bash
node --test test/test_ros2_status_ui.cjs
```
