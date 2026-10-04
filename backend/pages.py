import json
from pathlib import Path

from flask import Blueprint, current_app, render_template

from backend.database import get_database


blueprint = Blueprint("pages", __name__)


SYSTEM_CONFIG = (
    ("APP_ENV", "Application environment", "text"),
    ("PERSIST_DATABASE", "Persistent database", "boolean"),
    ("SERVER_ADDRESS", "Server address", "code"),
    ("SERVER_PORT", "Server port", "number"),
    ("ROS2_RUNNER_ADDRESS", "ROS 2 runner address", "code"),
    ("ROS2_RUNNER_PORT", "ROS 2 runner port", "number"),
    ("ROS2_COMMAND_TIMEOUT", "ROS 2 command timeout", "duration"),
    ("RECORDING_TIMEOUT_SECONDS", "Recording timeout", "duration"),
    ("TOPIC_MONITOR_WINDOW", "Topic monitor window", "window"),
    ("PERFORMANCE_POLL_INTERVAL_SECONDS", "Performance refresh interval", "duration"),
    ("DEBUG", "Debug mode", "boolean"),
    ("LOGGING_ENABLED", "Application logging", "boolean"),
    ("LOG_LEVEL", "Log level", "text"),
    ("DATABASE", "Database", "code"),
)


def _render_page(template, *, active_page, title, **context):
    return render_template(
        template,
        active_page=active_page,
        page_title=title,
        **context,
    )


def _recording_filesize(output_path):
    recording_path = Path(output_path)
    if not recording_path.exists():
        return None

    total_bytes = 0
    for path in recording_path.rglob("*"):
        if path.is_file():
            total_bytes += path.stat().st_size

    return total_bytes


def _format_size(size_bytes):
    if size_bytes is None:
        return "—"
    if size_bytes < 1000:
        return f"{size_bytes}B"

    units = ["KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    unit_index = -1
    while value >= 1000 and unit_index < len(units) - 1:
        value /= 1000.0
        unit_index += 1

    if value >= 10 or value.is_integer():
        return f"{int(round(value))}{units[unit_index]}"
    return f"{value:.1f}{units[unit_index]}"


def _format_duration(seconds):
    if seconds % 3600 == 0:
        value, unit = seconds // 3600, "hour"
    elif seconds % 60 == 0:
        value, unit = seconds // 60, "minute"
    else:
        value, unit = seconds, "second"
    return f"{value} {unit}{'' if value == 1 else 's'}"


def _format_config(value, kind):
    if kind == "boolean":
        return "Enabled" if value else "Disabled"
    if kind == "duration":
        return _format_duration(value)
    if kind == "window":
        return (
            f"Default {value['default']:,} messages; "
            f"range {value['min']:,}–{value['max']:,}"
        )
    if kind == "text" and isinstance(value, str):
        return value.replace("_", " ").title()
    return str(value)


def _recordings():
    rows = get_database().execute(
        """
        SELECT id, output_path, topics, status, started_at, finished_at
        FROM recordings
        ORDER BY started_at DESC, id DESC
        """
    ).fetchall()

    recordings = []
    for row in rows:
        try:
            topics = json.loads(row["topics"])
        except (TypeError, json.JSONDecodeError):
            topics = []
        if not isinstance(topics, list):
            topics = []

        recordings.append(
            {
                "id": row["id"],
                "output_path": row["output_path"],
                "display_name": Path(row["output_path"]).name,
                "status": row["status"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "topics": topics,
                "topic_count": len(topics),
                "topic_summary": ", ".join(topics) if topics else "No topics recorded",
                "size": _format_size(_recording_filesize(row["output_path"])),
            }
        )

    return recordings


@blueprint.get("/")
def index():
    return _render_page("index.html", active_page="dashboard", title="Dashboard")


@blueprint.get("/recordings")
def recordings_page():
    return _render_page(
        "recordings.html",
        active_page="recordings",
        title="Recordings",
        recordings=_recordings(),
    )


@blueprint.get("/system")
def system_page():
    settings = [
        {
            "key": key,
            "label": label,
            "value": _format_config(current_app.config[key], kind),
            "code": kind == "code",
        }
        for key, label, kind in SYSTEM_CONFIG
    ]
    return _render_page(
        "system.html",
        active_page="system",
        title="System",
        settings=settings,
    )
