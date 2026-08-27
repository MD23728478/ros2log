# ros2log



# Development

```bash
docker compose up --build
```

Open <http://localhost:5000>. Stop it with `Ctrl+C`.

Run the tests in another terminal:

```bash
docker compose run --rm app pytest
```

## Project structure

```text
backend/
  pages.py          Web page routes
  health.py         Docker healthcheck route
  api/              JSON API routes
  schema.sql        SQLite tables
frontend/
  templates/        Jinja HTML templates
  static/           CSS, JavaScript, and images
test/               Pytest tests
config.py           Project settings
```

## Add a web page

Add a route to `backend/pages.py`:

```python
@blueprint.get("/about")
def about():
    return render_template("about.html")
```

Create `frontend/templates/about.html`:

```html
{% extends "base.html" %}

{% block content %}
  <h1>About</h1>
{% endblock %}
```

Visit <http://localhost:5000/about>.

`base.html` contains the common HTML and loads Bootstrap. Other templates
extend it and fill its `content` block. Use Bootstrap classes in templates:

```html
<button class="btn btn-primary">Save</button>
```

Put project-specific styles in `frontend/static/css/app.css`.

## Add an API endpoint

Each API endpoint has its own file. Create `backend/api/customers.py`:

```python
from flask import jsonify

from backend.api import blueprint


@blueprint.get("/customers")
def customers():
    return jsonify(customers=[])
```

Import the new file at the bottom of `backend/api/__init__.py`:

```python
from backend.api import customers
```

Visit <http://localhost:5000/api/customers>.

## Add a database table

Add the table to `backend/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);
```

Use it in Python:

```python
from backend.database import get_database

database = get_database()
customers = database.execute("SELECT * FROM customers").fetchall()
```

The schema runs whenever the application starts.

## Change settings

Edit `config.py`. It controls development or production mode, database
persistence, server address, and server port.

If `SERVER_PORT` changes, update both numbers in the `ports` entry in
`compose.yaml` to match.

## Run tests

Docker installs pytest with the rest of the project dependencies, so nothing
needs to be installed on the host:

```bash
docker compose run --rm app pytest
```

The current tests validate the home page and example API response. Add test
files to `test/` as functionality is added.
