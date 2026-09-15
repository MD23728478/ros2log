import json
import sqlite3

import pytest

import config
from backend.app import create_app
from backend.database import get_database


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(
        config, "DATABASE", "file:database_test?mode=memory&cache=shared"
    )
    application = create_app()
    application.config["TESTING"] = True
    yield application
    application.extensions["database_keeper"].close()


def test_recordings_table_stores_recording_metadata(app):
    topics = ["/ros2log/test/temperature", "/ros2log/test/battery"]

    with app.app_context():
        database = get_database()
        database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            ("/storage/recording-test", json.dumps(topics), "started"),
        )
        row = database.execute(
            "SELECT output_path, topics, status, started_at, finished_at "
            "FROM recordings"
        ).fetchone()

    assert row["output_path"] == "/storage/recording-test"
    assert json.loads(row["topics"]) == topics
    assert row["status"] == "started"
    assert row["started_at"] is not None
    assert row["finished_at"] is None


def test_recordings_table_rejects_unknown_status(app):
    with app.app_context(), pytest.raises(sqlite3.IntegrityError):
        get_database().execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            ("/storage/recording-test", "[]", "unknown"),
        )
