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
