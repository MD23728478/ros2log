import json
from pathlib import Path

from flask import Blueprint, render_template

from backend.database import get_database


blueprint = Blueprint("pages", __name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _render_page(template, *, active_page, title, **context):
    return render_template(
        template,
        active_page=active_page,
        page_title=title,
        **context,
    )


def _recording_filesize(output_path):
    recording_path = PROJECT_ROOT / output_path.lstrip("/")
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


@blueprint.get("/topics")
def topics_page():
    return _render_page("topics.html", active_page="topics", title="Topics")


@blueprint.get("/recordings")
def recordings_page():
    return _render_page(
        "recordings.html",
        active_page="recordings",
        title="Recordings",
        recordings=_recordings(),
    )
