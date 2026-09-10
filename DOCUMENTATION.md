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
before `ROS2_COMMAND_TIMEOUT`; background process management is not implemented
yet.

`GET /api/ros2/health` checks whether the HTTP runner responds. It returns
`200` with `{"status": "ok"}` or `503` with `{"status": "unavailable"}`.

## Topic Monitor API

`GET /api/topic-monitor?topic=/ros2log/test/temperature` reads one message
from the named ROS topic through the existing HTTP runner. The `topic` query
parameter is required and must be a fully qualified name beginning with `/`.
There is no default topic or sample-data fallback.

The response has this shape (the type and message shown here are examples):

```json
{
  "source": "ros2",
  "topic": "/ros2log/test/temperature",
  "message_type": "std_msgs/msg/Float64",
  "latest_message": {"data": 23.7}
}
```

The API discovers the type using `ros2 topic type`, then uses
`ros2 topic echo --once` to receive a message. `latest_message` is the first
message received by that request's temporary subscription; it is not a cached
value or a continuous stream. The subscription uses best-effort reliability
and volatile durability, so it accepts live messages from both best-effort
and reliable publishers without requesting historical messages. Echo waits
up to five seconds for a message (less if the configured command timeout is
short). Discovery and startup also take time; each of the two commands is
bounded by `ROS2_COMMAND_TIMEOUT`.

ROS echo's YAML is safely parsed into JSON, preserving nested fields and full
arrays. Non-finite floating-point values become the strings `"nan"`, `"inf"`,
or `"-inf"`; binary YAML values become arrays of byte values. Responses use
`Cache-Control: no-store`. A UI can request another sample after the previous
request finishes, using the topic chosen in the topic list.

Errors return `{"error": "..."}` with these HTTP status codes:

| Status | Meaning |
| --- | --- |
| 400 | Missing or invalid topic name |
| 404 | Topic was not discovered |
| 409 | Topic has multiple message types |
| 502 | ROS command failed or its output could not be parsed |
| 503 | Runner could not complete the request, including runner command timeouts |
| 504 | Echo received no message within its waiting period |

To try the API with the development publishers, start Docker Desktop and run:

```bash
docker compose --profile development up --build
```

Open <http://localhost:5000/api/topic-monitor?topic=/ros2log/test/temperature>.
Refresh to request another reading, or change the topic to
`/ros2log/test/battery` or `/ros2log/test/status`. These are generated ROS
messages from the development publisher, not readings from a physical robot.
The same endpoint uses real robot topics when the runner is on a ROS host.

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
