# Development guide for agents

## Purpose

This repository is intentionally a minimal learning project. Keep changes
small, explicit, and readable by someone new to Flask, Jinja, Bootstrap,
SQLite, Docker, and pytest. Avoid abstractions until repeated code makes them
useful.

## Architecture

- `config.py` is the only configuration source. Do not add `.env` files,
  secrets, or environment-variable configuration unless the user asks.
- `backend/app.py` contains the Flask application factory and registers the
  page, health, and API blueprints.
- `backend/pages.py` contains ordinary HTML routes. `/` renders
  `frontend/templates/index.html`.
- `backend/health.py` owns `/health`. Docker Compose calls it as its
  healthcheck.
- `backend/api/__init__.py` defines the shared blueprint registered at `/api`.
- Each API endpoint or closely related endpoint group gets its own module in
  `backend/api/`. Import every new module from `backend/api/__init__.py` so its
  decorators run.
- `frontend/templates/base.html` is the common page layout. It loads Bootstrap
  from its CDN and the local `frontend/static/css/app.css` stylesheet.
- Page templates extend `base.html` and implement its Jinja blocks.
- `backend/schema.sql` is applied with `CREATE TABLE IF NOT EXISTS` statements
  whenever the app starts.
- `backend/database.py` provides request-scoped SQLite connections through
  `get_database()`.
- `test/` contains minimal pytest tests using Flask's test client.

## Configuration behavior

The editable values in `config.py` are:

- `APP_ENV`: `"development"` or `"production"`.
- `PERSIST_DATABASE`: `True` stores SQLite at `/storage/app.db`; `False` uses a
  shared in-memory SQLite database.
- `SERVER_ADDRESS`: bind address used by Flask or Gunicorn.
- `SERVER_PORT`: bind port used by Flask or Gunicorn and the healthcheck.

Derived values control debugging, logging, and the SQLite connection string.
The in-memory database needs its keeper connection in `app.extensions` because
shared SQLite memory is destroyed after its final connection closes.

Docker Compose publishes `5000:5000`. When changing `SERVER_PORT`, update both
the target and published ports in `compose.yaml` as well. The healthcheck reads
`SERVER_PORT` directly from `config.py`.

## Docker behavior

- `docker/Dockerfile` installs `requirements.txt` and copies the application,
  frontend, tests, and startup script.
- `docker/start.sh` reads `config.py`. Development uses Flask's debug server;
  production uses Gunicorn.
- `./storage` is mounted at `/storage` for a host-persistent SQLite database.
- Start with `docker compose up --build`.

## How to extend the project

For a normal page:

1. Add a route to `backend/pages.py`.
2. Add its Jinja template under `frontend/templates/`.
3. Extend `base.html` rather than repeating the page shell.
4. Add route validation to `test/`.

For an API endpoint:

1. Add a clearly named module under `backend/api/`.
2. Import the shared `blueprint` from `backend.api`.
3. Define its route without `/api`; the registered prefix supplies it.
4. Import the new module at the bottom of `backend/api/__init__.py`.
5. Test status codes and exact JSON shapes.

For database changes:

1. Add idempotent SQL to `backend/schema.sql`.
2. Access SQLite with `get_database()`.
3. Commit writes explicitly.
4. Add focused data validation tests.

## Style

- Prefer direct Flask functions and standard-library SQLite.
- Keep one obvious way to perform each task.
- Use type hints where they clarify interfaces, not as ceremony.
- Avoid comments and docstrings that only repeat names or code. Document
  non-obvious lifecycle or architectural constraints here instead.
- Do not add authentication, migration frameworks, JavaScript frameworks,
  ORMs, or other infrastructure without a feature that needs them.
- Preserve the separate `backend/`, `frontend/`, `docker/`, and `test/`
  directories.

## Verification

Run checks appropriate to the change:

```bash
python3 -m compileall -q config.py backend test
sh -n docker/start.sh
git diff --check
docker compose config
docker compose run --rm app pytest
```

The project is Docker-first. Host Python may not have Flask or pytest. If image
or package downloads are blocked, still run dependency-free syntax, SQL, shell,
and Compose validation and report the unavailable runtime check.

Do not modify or restore unrelated user changes. In particular, check
`git status --short` before editing and preserve existing worktree state.
