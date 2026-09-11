# Development documentation

## Project structure

```text
backend/
  app.py              Flask application factory
  pages.py            HTML routes
  health.py           Docker healthcheck route
  api/                 JSON API routes
  database.py          Request-scoped SQLite connections
  schema.sql           Idempotent database schema
frontend/
  templates/           Jinja templates
  static/              CSS and JavaScript
docker/
  Dockerfile           Flask application image
  ros2.Dockerfile      Jazzy development image
test/                   Pytest tests
config.py               Project settings
compose.yaml            Production and development services
runner/                  ROS 2 command client and runner server
```

`backend/app.py` registers the page, health, and API blueprints. The API
blueprint is mounted at `/api`. The development-only `ros2` Compose profile
runs the runner and continuously publishes random test topics.

## Add a page

1. Add its route to `backend/pages.py`.
2. Add its template under `frontend/templates/`.
3. Extend `base.html` instead of repeating the page shell.
4. Add a focused route test under `test/`.

```python
@blueprint.get("/about")
def about():
    return render_template("about.html")
```

```html
{% extends "base.html" %}

{% block content %}
  <h1>About</h1>
{% endblock %}
```

## Add an API endpoint

1. Add a clearly named module under `backend/api/`.
2. Import the shared `blueprint` from `backend.api`.
3. Define its route without `/api`; the registered prefix supplies it.
4. Import the module at the bottom of `backend/api/__init__.py`.
5. Test status codes and exact JSON shapes.

```python
from flask import jsonify

from backend.api import blueprint


@blueprint.get("/customers")
def customers():
    return jsonify(customers=[])
```

## Run a ROS 2 command

Routes may use the generic synchronous command helper:

```python
from runner.client import ros2_command

result = ros2_command("node", "list")
```

Arguments are passed directly to `ros2` without a shell. Commands must finish
before `ROS2_COMMAND_TIMEOUT` by default; background process management is not
implemented. For commands such as `topic hz` and `topic bw`, the optional
`capture_on_timeout=True` argument stops the command after `timeout_seconds`
and returns its captured output with `return_code: 124` and `timed_out: true`.
Commands that finish earlier return their actual exit code and
`timed_out: false`. Without this option, command timeouts still return a runner
HTTP 504 error. The runner uses unbuffered Python output so measurements are
available before the command ends. Both the app and runner need this update.

`GET /api/ros2/health` checks whether the HTTP runner responds. It returns
`200` with `{"status": "ok"}` or `503` with `{"status": "unavailable"}`.

### Run a background ROS 2 command

Long-running commands use a separate runner interface. This does not change
the behavior or response format of the synchronous command helper above.

```python
from runner.client import (
    ros2_background_command_forget,
    ros2_background_command_start,
    ros2_background_command_status,
    ros2_background_command_stop,
)

command = ros2_background_command_start(
    "bag",
    "record",
    "--output",
    "/storage/recordings/example",
    "/example/topic",
    timeout_seconds=3600,
)
command = ros2_background_command_status(command["command_id"])
command = ros2_background_command_stop(command["command_id"])
ros2_background_command_forget(command["command_id"])
```

The matching runner endpoints are:

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/background-command` | Starts a command and returns `201` with its state |
| `GET` | `/background-command/<command_id>` | Returns its current state and output tails |
| `POST` | `/background-command/<command_id>/stop` | Interrupts it and returns its final state |
| `DELETE` | `/background-command/<command_id>` | Forgets a finished command |

Start requests contain `arguments` and a mandatory positive
`timeout_seconds`. The timeout is enforced by the runner even when the Flask
application is unavailable. Status responses contain `state` (`running`,
`stopping`, or `finished`), `return_code`, the most recent 64 KiB of stdout and
stderr, truncation flags, `termination_reason` (`manual`, `timeout`, or null),
and `forced`. Stopping sends `SIGINT` to the command's process group so ROS 2
can finalize its files. If it has not exited after 30 seconds, the runner uses
`SIGKILL` and reports `forced: true`.

Background command IDs and process handles exist only in runner memory. They
survive a Flask restart while the runner remains active, but not a runner
restart. Finished commands remain available until explicitly forgotten or the
runner exits. On a graceful runner shutdown, active commands are interrupted.

### Recording design for the Flask API

Recording is intentionally an application concern rather than a special
runner operation. A future Flask implementation should:

1. Generate and persist its own recording ID, independently of the ephemeral
   runner command ID.
2. Validate requested topics and enforce one active recording at a time.
3. Start `ros2 bag record --output /storage/recordings/<recording-id> ...`
   through `ros2_background_command_start`, supplying a safety deadline.
4. Persist the topics, both IDs, timestamps, output path, and application-level
   recording state in SQLite.
5. On progress requests, poll the runner and combine its process state and log
   tail with elapsed time and the size of the bag under `/storage`.
6. On stop requests, call the background stop helper, save the final result,
   and forget the runner command after its result has been harvested.

A Flask-only restart can reconnect using the persisted runner command ID. If
the runner has restarted and returns `404`, Flask should mark the recording as
interrupted; any bag data already written remains in `/storage`. A natural
zero exit maps to completed, a manual interrupt to stopped, a deadline to
timed out, and a nonzero exit or forced kill to failed. This future Flask work
will require a database schema change. The runner change itself does not alter
the database.

The development app and ROS 2 containers share `./storage` at `/storage`.
Production must likewise make the same physical storage available to both the
Flask container and the host runner at `/storage`.

## Topic Monitor API

`GET /api/topic-monitor?topic=/ros2log/test/temperature` measures frequency
and bandwidth for the named topic through the existing HTTP runner. The `topic` query
parameter is required and must be a fully qualified name beginning with `/`.
There is no default topic or sample-data fallback.

The response has this shape (the numbers shown here are illustrative):

```json
{
  "source": "ros2",
  "topic": "/ros2log/test/temperature",
  "frequency_hz": 2.0,
  "bandwidth_bytes_per_second": 32.0
}
```

The API checks that the topic exists using `ros2 topic type`, then runs
`ros2 topic hz --wall-time` and `ros2 topic bw` sequentially. Each measurement
uses a window of up to 100 messages and a five-second command budget (or
`ROS2_COMMAND_TIMEOUT`, if shorter). Requests normally take about ten seconds
plus the initial topic lookup. Startup and discovery are included in each
measurement budget, so slow or inactive topics can produce insufficient data.

The latest complete statistics line from each command is parsed. Frequency
is in Hz (messages per second). Bandwidth is serialized message bytes per
second, not bits per second or total network traffic including DDS overhead.
ROS's decimal units are normalized: 1 KB/s = 1000 B/s, 1 MB/s = 1000000 B/s.
These are receiving measurements from two successive sampling periods;
resource limits and QoS can make them differ from the publisher's rate.
Message payloads are not returned. See the ROS implementations of
[hz](https://github.com/ros2/ros2cli/blob/jazzy/ros2topic/ros2topic/verb/hz.py)
and [bw](https://github.com/ros2/ros2cli/blob/jazzy/ros2topic/ros2topic/verb/bw.py).

Responses use `Cache-Control: no-store`. The UI should wait for a request to
finish before requesting another sample, and show missing measurements as
unavailable rather than treating them as zero.

Errors return `{"error": "..."}` with these HTTP status codes:

| Status | Meaning |
| --- | --- |
| 400 | Missing or invalid topic name |
| 404 | Topic was not discovered |
| 409 | Topic has multiple message types |
| 502 | ROS command failed or its output could not be parsed |
| 503 | Runner could not complete the request, including runner command timeouts |
| 504 | Not enough traffic to obtain a measurement within the sampling period |

To try the API with the development publishers, start Docker Desktop and run:

```bash
docker compose --profile development up --build
```

Open <http://localhost:5000/api/topic-monitor?topic=/ros2log/test/temperature>.
Refresh to measure again, or change the topic to `/ros2log/test/battery` or
`/ros2log/test/status`. The development publisher sends each topic at about
2 Hz, so frequency should be near 2.0. Bandwidth depends on serialized message
size. These measurements use traffic generated by a ROS test publisher;
the same endpoint measures robot topics when the runner is on a ROS host.

## Change the database

1. Add idempotent SQL to `backend/schema.sql`.
2. Use `get_database()` for request-scoped access.
3. Commit writes explicitly.
4. Add focused validation tests.

```python
from backend.database import get_database

database = get_database()
rows = database.execute("SELECT * FROM example_items").fetchall()
```

The schema is applied whenever the application starts. A shared in-memory
database requires the keeper connection stored in `app.extensions` because
SQLite destroys it after its final connection closes.

## Frontend

Page templates extend `frontend/templates/base.html`. It provides the shared
layout and loads Bootstrap and `frontend/static/css/app.css`. Keep
project-specific styling in `app.css`.
