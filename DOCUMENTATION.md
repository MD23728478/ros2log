# DOCUMENTATION

This document describes the current code, its contracts, and the places to change when adding behavior. [README.md](README.md) is the operator setup guide. Code is the source of truth if a deployment differs from the defaults here.

## How the application fits together

```text
Browser
  ├─ HTML and static assets ← Flask pages (`backend/pages.py`)
  └─ JSON requests          → Flask API (`backend/api/`)
                                  ├─ SQLite and mounted bag files
                                  └─ runner client (`runner/client.py`)
                                           │ HTTP
                                           ▼
                                    runner server (`runner/server.py`)
                                           ├─ `ros2` subprocesses
                                           └─ host/container metrics
```

The Flask app runs in the `app` container. In development, Compose also runs a Jazzy `ros2` container with the runner and sample publishers. In production, the runner runs on a ROS 2 host; the app reaches it through `host.docker.internal` by default. The app never runs the ROS CLI itself. The runner provides synchronous commands, one managed background command, health, and metrics over HTTP.

| Area | Main files | Responsibility |
| --- | --- | --- |
| Configuration | `config.py`, `compose.yaml`, `docker/` | Mode, ports, paths, images, mounts, startup |
| Flask setup | `backend/app.py`, `backend/health.py` | App factory, blueprints, health check |
| HTML | `backend/pages.py`, `frontend/templates/` | Dashboard, Recordings, System pages |
| JSON API | `backend/api/` | Topic discovery, monitoring, recording, metadata, performance |
| Persistence | `backend/database.py`, `backend/schema.sql` | SQLite connections and schema |
| ROS boundary | `runner/client.py`, `runner/server.py` | HTTP protocol and ROS subprocess lifecycle |
| Metrics | `runner/metrics.py` | CPU, memory, uptime, and filesystem readings |
| Browser behavior | `frontend/static/js/` | Fetching, UI state, polling, rendering |
| Tests | `test/` | Flask, runner, metadata, and optional browser coverage |

`create_app()` loads uppercase values from `config.py`, initializes the database, then registers the page, health, and API blueprints. All API routes use the `/api` prefix supplied by the app factory. The runner routes have no `/api` prefix.

## Configuration and runtime

Edit settings in `config.py`. It defines `APP_ENV` (`development` or `production`), ports and addresses, the ROS executable and timeouts, storage paths, database mode, monitoring window, and browser performance poll interval. Several values are derived when the module is imported: `DEBUG`, logging options, `ROS2_RUNNER_ADDRESS`, and `DATABASE`. If you change a value on a live process, restart that process. Both Docker images copy `config.py` at build time, so rebuild them after changing it.

The `app` image runs as UID/GID `10001:10001`. `docker/start.sh` uses Flask's development server in development and Gunicorn in production; its lowercase `gunicorn_*` environment variables tune workers, threads, and timeouts. The `ros2` development image starts the runner and a publisher for three `/ros2log/test/*` topics. The host runner must be started from an environment where the intended ROS installation and workspace are sourced. `ROS2_EXECUTABLE_PATH = None` selects `ros2` from `PATH`; a configured executable path applies to both finite and background commands.

The runner defaults to listening on `0.0.0.0:8765`; the app connects to `ros2:8765` in development or `host.docker.internal:8765` in production. `compose.yaml` supplies the production host alias. The runner HTTP server has no authentication layer; treat its listen address and network reachability as part of deployment configuration.

### Storage is one physical directory with two path names

| Process | Path setting | Default | Use |
| --- | --- | --- | --- |
| Flask container | `STORAGE_PATH` | `/storage` | SQLite `app.db`, listing, metadata, rename, delete |
| Production host runner | `RUNNER_STORAGE_PATH` | `./storage` beside `config.py` | `ros2 bag record` output and runner disk metric |
| Development runner container | `STORAGE_PATH` | `/storage` | Shared mounted bag output and runner disk metric |

The Compose bind mount maps the host directory to `/storage` in the app container (and in the development runner container). In production, Flask builds a recording name under `STORAGE_PATH`; the runner translates the `--output` argument of `bag record` to the corresponding path under `RUNNER_STORAGE_PATH`. This translation only occurs for production background `bag record` commands. The runner resolves a relative host path against the directory containing `config.py`, creates the host storage directory when starting a recording or collecting production metrics, and reports its resolved path in metrics.

SQLite stores the **container** path such as `/storage/recording-20261010-120000`. The production dashboard and Recordings page derive a host display path from that value; there is no second database path. Keep the host side of the Compose mount and `RUNNER_STORAGE_PATH` pointed at the same physical directory. If the container path changes, existing database rows still contain the old absolute path; moving the files alone does not rewrite those rows. Moving `STORAGE_PATH` also moves the configured `app.db` path. The Flask UID must be able to write the database and read/manage bag directories, and the host runner user must be able to write bag output. A writable top-level directory does not necessarily make new bag subdirectories writable for Flask's Delete action.

### SQLite lifecycle

`backend/database.py` opens one connection per Flask request context through `get_database()` and closes it at teardown. Call `commit()` after writes. `init_app()` applies `backend/schema.sql` at startup. Its `IF NOT EXISTS` statements create missing objects; they are **not** a migration system for existing table definitions. The `recordings` table stores path, topics JSON, state (`started`, `finished`, or `failed`), and timestamps. A partial unique index allows only one `started` row, matching the runner's single background slot. `PERSIST_DATABASE = False` uses a shared in-memory SQLite URI and a keeper connection; that arrangement is for tests/development, not persistence across restarts or separate Gunicorn workers.

## HTTP and process contracts

### Flask endpoints

| Method and path | Source | Purpose |
| --- | --- | --- |
| `GET /`, `/recordings`, `/system` | `backend/pages.py` | Render pages |
| `GET /health` | `backend/health.py` | App/container health |
| `GET /api/ros2/health`, `/api/ros2/status` | `backend/api/ros2.py` | Runner reachability and a separate ROS graph probe |
| `GET /api/topics` | `backend/api/topic_list.py` | List ROS topics, including hidden topics |
| `GET /api/topic-monitor` | `backend/api/topic_monitor.py` | Measure one topic's frequency and bandwidth |
| `POST /api/record/start`, `GET /api/record/status`, `POST /api/record/stop` | `backend/api/topic_record.py` | Start, reconcile, and stop a bag recording |
| `POST /api/recordings/<id>/rename`, `/delete` | `backend/api/recordings.py` | Manage a saved bag directory and database row |
| `GET /api/recordings/<id>/metadata` | `backend/api/recording_metadata.py` | Parse a recorded bag's `metadata.yaml` |
| `GET /api/performance` | `backend/api/performance.py` | Combine app and runner metrics |

Errors generally return JSON with an `error` field. Check each route's status codes before changing a client: callers distinguish invalid input, missing data, conflicts, runner failure, and insufficient ROS traffic. `GET /api/ros2/health` only checks the HTTP runner; `/api/ros2/status` also executes a ROS topic-list probe and distinguishes `available`, `ros2_unavailable`, and `runner_unavailable`.

### Runner endpoints and client helpers

| Method and path | Client helper | Behavior |
| --- | --- | --- |
| `GET /health` | `ros2_runner_is_healthy()` | HTTP runner check |
| `POST /command` | `ros2_command(...)` | Run one finite ROS command |
| `POST /background-command` | `ros2_background_command_start(...)` | Start one managed process; `409` if busy |
| `GET /background-command` | `ros2_background_command_status()` | Current/last background state; `404` if never started |
| `POST /background-command/stop` | `ros2_background_command_stop()` | Stop and wait for the process |
| `GET /metrics` | `runner_metrics()` | Runner environment and storage filesystem metrics |

The client in `runner/client.py` validates arguments and timeout values, sends JSON over `urllib`, validates response shapes, and raises its own exception types. Commands use `subprocess` argument lists with `shell=False`; pass arguments without a leading `ros2`. For a finite command, `ROS2_COMMAND_TIMEOUT` is the default; the client waits one extra second for the HTTP response. A normal timeout becomes runner HTTP `504`. With `capture_on_timeout=True`, the runner ends the process and returns captured output, `return_code: 124`, and `timed_out: true`. That mode exists for the continuously running `topic hz` and `topic bw` commands. The runner sets `PYTHONUNBUFFERED=1` because the ROS Python CLI must flush a measurement before being stopped. `TimeoutExpired` may contain bytes despite `text=True`; the runner decodes those before returning JSON.

The background slot is in memory and holds at most one process. It captures up to the last 64 KiB of each output stream, with truncation flags. Stop sends SIGINT to the process group, waits up to 30 seconds, then sends SIGKILL if needed. The configured recording timeout invokes the same stop path with reason `timeout`. A finished result remains available until another command replaces it or the runner restarts. The runner prints requests, command launches, and background start/stop/exit events to stdout. It does not print captured command stdout/stderr; those appear in HTTP responses.

### Recording state transition

`POST /api/record/start` validates fully qualified topic names, an optional safe filename prefix, and an optional positive duration bounded by `RECORDING_TIMEOUT_SECONDS`. It inserts a `started` row **before** asking the runner to start `ros2 bag record --output ... --topics ...`. If the runner start call fails, the route deletes that new row. The runner returns `409` when its background slot is busy. The database also has a unique index on `started`; an attempt to insert while a `started` row already exists raises a SQLite integrity error that this route does not currently translate into a JSON conflict. Recording names use timestamps to the second, so a repeated name in that second can also collide with the unique path constraint.

`GET /api/record/status` polls the runner and reconciles the latest `started` database row. A finished process is marked `finished` only if it exited with code zero after a manual stop or timeout; otherwise it is `failed`. Runner status errors also mark an active row failed. `POST /api/record/stop` waits for the stop result and marks a zero-exit recording finished. The runner's in-memory state and SQLite are separate; a runner restart loses the background slot, and a stale `started` row must be reconciled or investigated. The response from start includes the stored container `output` and a production `display_output` for the browser.

The Recordings page reads database rows, calculates directory sizes from the container path, and manages folders through Flask. Rename changes the folder and then the database path. Delete removes the folder and then the row. Metadata lookup requires an existing row; simply copying a bag into storage does not make it appear on the page.

### Recording metadata

`GET /api/recordings/<id>/metadata` looks up the database path, requires a non-active recording, and confines its resolved metadata file to `STORAGE_PATH`. `backend/rosbag_metadata.py` uses `yaml.safe_load` and normalizes ROS bag metadata versions **4–9**. It returns `summary`, `topics`, `files`, and `advanced`; it normalizes QoS policy values and turns nanosecond counts into decimal **strings** as well as seconds where useful, avoiding JavaScript integer precision loss. Versions before 5 use `relative_file_paths`; later versions use the `files` records. Invalid, unsupported, or out-of-storage metadata paths return `422`; missing rows/directories/files return `404`; active recordings return `409`.

### Topic monitor

`GET /api/topic-monitor?topic=/some/topic&window=100` requires a fully qualified topic name. The window defaults to `TOPIC_MONITOR_WINDOW.default` and must be one ASCII whole number within the configured bounds (currently 2–10000); repeats and invalid values return `400`. The lower bound gives the bandwidth command enough messages. The endpoint checks `ros2 topic type` first. Jazzy reports a missing topic as exit code 1 with empty output; other failures are upstream errors. Multiple message types return `409`.

The endpoint samples `ros2 topic hz --wall-time` and then `ros2 topic bw`, each for at most five seconds or `ROS2_COMMAND_TIMEOUT`, whichever is shorter. It parses the latest **complete** statistics line and converts ROS decimal `B`, `KB`, and `MB` per second to bytes per second. The two readings are sequential receiving measurements, so they need not be from the same messages or match the publisher exactly. The requested window is a maximum retained message count, not a sampling duration or an actual received count. Empty or malformed measurements have distinct errors from ROS command failures; too little traffic returns `504`.

## Browser state and rendering

`frontend/templates/base.html` loads Bootstrap, `app.css`, and the performance poller on every page. The dashboard includes topic list, recording controls, and monitor partials. Keep project styling in `frontend/static/css/app.css`; the `bootstrap*.min.*` files are vendored assets. The JavaScript is plain browser JS, organized by page or component.

- `topic-list.js` fetches topics, retains checked topics across search, removes selections that disappear on refresh, and broadcasts `topics:selected`. Recording and monitor controls both subscribe to that event.
- `topic-monitor.js` keeps one active selected topic. Search and selecting another topic do not clear an unchanged reading. Changing the active topic or window stops Auto and invalidates an in-flight reply using `selectionRevision`. Auto waits for each request to finish, then delays three seconds; it never overlaps measurement requests. Errors clear values and stop Auto.
- `topic-recording.js` posts start/stop and polls recording status every two seconds while active. Its elapsed timer uses `localStorage`; failure to access browser storage does not break the page. The timer is a UI clock, not the authoritative process duration.
- `ros2-status.js` checks `/api/ros2/status` repeatedly, roughly every five seconds after each result, without blocking recording controls.
- `recordings.js` handles rename, delete, and the metadata dialog. It uses recording IDs from rendered rows and writes text through `textContent`.
- `performance-poller.js` runs on every page, polls at `PERFORMANCE_POLL_INTERVAL_SECONDS`, retains the latest result and at most 30 CPU/memory samples per target in `sessionStorage`, and falls back to in-memory state if browser storage is unavailable. `system.js` renders those events. No performance history is saved in SQLite.

The System page displays container **free space** for filesystem `/` and runner **used space** for the runner's storage filesystem. `runner/metrics.py` calls `shutil.disk_usage(path)`: this measures the filesystem containing the path, not the sum of files in that directory. Two paths on the same physical disk can report the same total/usage. CPU, memory, uptime, and storage may independently be `null` if unavailable; the runner client validates the overall metrics shape. A production runner storage failure is printed with the attempted path, while the UI renders that metric as unavailable. Click **Poll** or wait for the browser interval after restarting processes.

## How to add or change behavior

### Add a JSON endpoint

1. Add a module under `backend/api/`, import the shared `blueprint`, and register a route **without** `/api` in its path.
2. Import the new module at the bottom of `backend/api/__init__.py`; otherwise its decorators are never registered.
3. Use `current_app.config` for app settings, `get_database()` for request-scoped SQLite, and a `runner.client` helper for ROS work. Validate input before starting a runner command.
4. Return explicit JSON and status codes. Test success, invalid input, and relevant runner or filesystem failures in `test/`.

### Add a page or frontend interaction

1. Add the page route in `backend/pages.py`, or add a partial to the existing dashboard if it belongs there.
2. Extend `frontend/templates/base.html`, use the shared sidebar, and add page-specific JS under `frontend/static/js/` if needed.
3. Put project styles in `app.css`. Keep shared selection and polling events intact when adding UI controls.
4. Add a route test and a browser interaction test when timing, selection, or navigation is material.

### Add ROS work

Use `ros2_command()` for a bounded operation. For a command that runs continuously but prints periodic results, supply a finite timeout and `capture_on_timeout=True`; test both early exit and timeout output. A long-running managed operation must use the background helpers and account for the **single slot**. If you change the runner HTTP response or storage argument translation, update both `runner/server.py` and `runner/client.py`, plus their tests. Keep subprocess arguments as a list; do not build a shell command string.

### Change persistence or metadata

Edit `backend/schema.sql` for new installations and design a separate migration for existing databases when changing an existing table. Use `get_database()` and commit writes. Preserve the invariant of one active recording unless you redesign the runner slot and reconciliation together. For metadata format changes, update `backend/rosbag_metadata.py`, its endpoint contract, and versioned fixtures/tests. Preserve path confinement and string handling for precise nanoseconds.

### Change configuration or deployment

Edit `config.py`, then trace derived values, both Dockerfiles, `compose.yaml`, the host runner, and browser settings. Changing a host storage location requires a matching Compose bind mount. Changing the container storage path can invalidate existing database rows and must also account for the persistent database location. Rebuild images that copy config and restart the host runner. The app image's `/storage` ownership at build time does not override permissions of the mounted host directory.

## Test and validation workflow

```bash
# Python suite without collecting the ROS publisher script
pytest -q test

# Same suite in the app image
docker compose run --build --rm app pytest -q test

# Node regression checks for the ROS status UI
node --test test/test_ros2_status_ui.cjs
```

A bare `pytest` from the repository root can collect `docker/ros2/test_topics.py`, which imports `rclpy`; use `pytest test` when ROS Python packages are absent. The Python tests mock the ROS process or exercise the HTTP runner locally, so most do not need a running ROS graph. For a live end-to-end check, run the development profile and use the `/ros2log/test/temperature`, `/battery`, or `/status` publishers (about 2 Hz).

Optional Playwright checks live in `test/test_topic_monitor_ui.py`; they skip if `playwright.sync_api` is absent. Install Playwright and Chromium, or set `ROS2LOG_BROWSER_CHANNEL=chrome` to use a local Chrome. `ROS2LOG_UI_ARTIFACT_DIR` selects a screenshot output directory. These checks serve the Flask page with simulated API replies and verify selection, Auto timing, errors, timer navigation, and narrow layout; they do not verify a live ROS graph.

## FAQ and pitfalls

**Why is the runner healthy but ROS marked unavailable?** `/health` only proves the HTTP process responds. `/api/ros2/status` also probes `ros2 topic list`. Check the runner's ROS environment, executable path, domain/discovery settings, and its stdout logs.

**Why is runner storage “Not available” after recording?** Inspect `GET /metrics` on the runner and its stdout for `Storage metrics unavailable for <path>: <error>`. The production runner chooses the host path only when its own `APP_ENV` is `production`; otherwise it measures `STORAGE_PATH` (`/storage` by default). Check the config used by the running host process, restart it after changes, and verify the resolved path exists and is accessible. The System page may be showing a cached browser sample until **Poll** runs. Starting a recording creates the directory but does not itself prove `shutil.disk_usage` succeeds. `runner/client.py` also validates the metrics response; a shape mismatch can make the whole runner target unavailable.

**Why are container and runner disk totals identical?** `shutil.disk_usage` reports filesystem capacity. The container overlay and host storage mount may be backed by the same physical disk. The container card uses `/` and shows available space; the runner card uses its storage path and shows used space. These are not per-directory bag sizes.

**Why does recording appear in SQLite but not on disk, or vice versa?** The row is inserted before the runner starts and deleted if that start call fails. Runner state is in memory, while SQLite persists. A runner restart, path/mount mismatch, permissions, or external file copy can separate them. The Recordings page only lists rows; inspect its container path, the host path, and the runner's startup output. An externally copied bag needs a database row before the page or metadata endpoint can find it.

**Why can Flask read a bag but fail to delete it?** The app runs as UID/GID 10001, and a bind mount uses host permissions. The host runner may create subdirectories without group write permission even if the top-level directory is `775`. `shutil.rmtree` needs write access inside those directories. Review ownership and permissions on the actual recording folder, not only the mount root.

**Why does a monitor request take around ten seconds or return insufficient data?** Topic type lookup precedes two sequential, up-to-five-second samples. Discovery time and traffic arrival consume each budget. The browser Auto delay starts only after the request finishes. The `window` controls retained message count; increasing it does not extend the sampling time.

**Why was a command's output kept after a timeout?** `capture_on_timeout=True` is deliberate for `hz` and `bw`, which usually never exit by themselves. In that case `return_code: 124` plus `timed_out: true` is a sampling result, not an early ROS failure. Without that flag, a timeout is an HTTP `504`. The runner forces unbuffered Python output and decodes timeout output that arrives as bytes.

**Why does a finished recording still show as active, or a new one conflict?** The runner retains its final result until replaced, while SQLite has a unique `started` row. Status polling performs reconciliation. Check `/api/record/status`, the runner's `/background-command`, and the database row. The browser's elapsed timer is local UI state and does not change either source of truth.

**Why does a metadata file return `422`?** The parser only supports metadata versions 4–9 and validates required fields, QoS forms, and numeric ranges. The endpoint also rejects paths that escape `STORAGE_PATH`. Preserve nanosecond strings when consuming the API; JavaScript numbers cannot represent all such integers exactly.

**Why does a config or frontend change not appear after restart?** Both Docker images copy `config.py`, while the app image copies frontend assets, at build time; rebuild the affected image. The host runner is a separate process and must also restart for its config/code changes. Browser `sessionStorage` may still hold the last System reading until a new poll.

**Why are host CPU or uptime readings unavailable while disk works?** `runner/metrics.py` reads Linux `/proc` and cgroup files for those values. It catches platform read failures separately, so disk usage may still be available on a non-Linux host. Its process-start calculation parses `/proc/1/stat` after the final `)` because process names can contain spaces.

**Why does the test suite fail while importing `rclpy`?** Root-level collection can include `docker/ros2/test_topics.py`. Run `pytest test` for the application suite, or run ROS-dependent checks in the Jazzy image.
