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

The runner manages one background command at a time. Starting another while it
is active returns `409`. A finished command is replaced by the next start.

```python
from runner.client import (
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
command = ros2_background_command_status()
command = ros2_background_command_stop()
```

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/background-command` | Starts a command and returns `201` with its state |
| `GET` | `/background-command` | Returns its state and output |
| `POST` | `/background-command/stop` | Stops it and returns its final state |

TL;DR: The runner owns one background ROS 2 command at a time. Start, inspect,
or stop it without an ID. Its final state remains available until it is replaced
or the runner restarts.

## Topic Monitor API

`GET /api/topic-monitor?topic=/ros2log/test/temperature` measures frequency
and bandwidth for the named topic through the existing HTTP runner. The `topic` query
parameter is required and must be a fully qualified name beginning with `/`.
There is no default topic or sample-data fallback.

The optional `window` query parameter sets the maximum number of recent messages
used by each ROS measurement command, for example:
`GET /api/topic-monitor?topic=/ros2log/test/temperature&window=250`.
It must be a whole number from 2 to 10000, and defaults to 100 when omitted.
Empty, invalid, out-of-range, and repeated `window` parameters return HTTP 400
before any ROS command starts. The lower bound allows the bandwidth command to
retain at least two messages; the upper bound limits its retained sample count.
The default and limits live in `config.py` under `TOPIC_MONITOR_WINDOW` and are
also rendered into the dashboard form.

The response has this shape (the numbers shown here are illustrative):

```json
{
  "source": "ros2",
  "topic": "/ros2log/test/temperature",
  "window": 100,
  "frequency_hz": 2.0,
  "bandwidth_bytes_per_second": 32.0
}
```

The API checks that the topic exists using `ros2 topic type`, then runs
`ros2 topic hz --wall-time` and `ros2 topic bw` sequentially. Each measurement
uses the requested message window and a five-second command budget (or
`ROS2_COMMAND_TIMEOUT`, if shorter). Requests normally take about ten seconds
plus the initial topic lookup. Startup and discovery are included in each
measurement budget, so slow or inactive topics can produce insufficient data.
The window is a message count, not a duration or a promise to collect that many
messages. Increasing it does not extend the command budget. The response's
`window` field reports the requested limit, not the actual number received.

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
Check topics in the topic list, choose one in the monitor dropdown, and set the
message window before measuring. The same checked topics remain available to
the recording controls; choosing a monitor topic does not change that selection.
Searching the list or checking another topic preserves the active monitor topic
and reading. Removing the active topic switches to the first remaining selection
and clears its old reading; removing every selection disables the monitor.

The dashboard provides separate frequency/bandwidth readings and loading/error
states, styled in `frontend/static/css/topic-monitor.css`. Auto starts a reading
immediately, then waits three seconds after each request finishes before starting
the next one. Stopping
Auto lets the current request finish but schedules no further readings.
Changing the topic or window stops Auto and clears the old result. Any pending
response for the previous settings is ignored; a new request can start when
that pending request finishes. Errors clear the readings and stop Auto.

Errors return `{"error": "..."}` with these HTTP status codes:

| Status | Meaning |
| --- | --- |
| 400 | Missing/invalid topic name or invalid window |
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

### Browser checks for the monitor

Backend and runner tests use the normal pytest setup. The optional browser
regression tests in `test/test_topic_monitor_ui.py` use Playwright and skip when
that Python package is absent. Install it in a development/test environment:

```bash
python -m pip install playwright
python -m playwright install chromium
python -m pytest test/test_topic_monitor_ui.py
```

To use an installed Chrome instead, set `ROS2LOG_BROWSER_CHANNEL=chrome` when
running the tests; the Chromium download is then unnecessary. The tests serve
the real Flask page and its assets while simulating API replies. They cover
shared topic selection with the dropdown and recording controls, window
submission/validation, Auto scheduling and Stop, changing settings during a
pending request, errors, and a narrow monitor column. They do not replace a
live ROS measurement check. An optional `ROS2LOG_UI_ARTIFACT_DIR` directory
receives screenshots from the browser checks.

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
