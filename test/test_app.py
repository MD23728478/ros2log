import json
import shutil
from pathlib import Path
from uuid import uuid4

import config

from backend.app import create_app
from backend.database import get_database


def test_pages_and_api():
    config.PERSIST_DATABASE = False
    config.DATABASE = "file:test?mode=memory&cache=shared"
    client = create_app().test_client()

    page = client.get("/")
    assert page.status_code == 200
    assert b"Dashboard" in page.data

    topics = client.get("/topics")
    assert topics.status_code == 200
    assert b"Topics" in topics.data

    recordings = client.get("/recordings")
    assert recordings.status_code == 200
    assert b"Recordings" in recordings.data

    api = client.get("/api/hello")
    assert api.status_code == 200
    assert api.get_json() == {"message": "Hello from the API"}


def test_recordings_page_lists_saved_recordings(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", "file:recordings_page_test?mode=memory&cache=shared")
    application = create_app()
    application.config["TESTING"] = True

    with application.app_context():
        database = get_database()
        database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            (
                "/storage/recording-20260924-055416",
                json.dumps(["/ros2log/test/temperature", "/ros2log/test/battery"]),
                "finished",
            ),
        )
        database.commit()

    response = application.test_client().get("/recordings")
    assert response.status_code == 200
    assert b"recording-20260924-055416" in response.data
    assert b"/ros2log/test/temperature" in response.data
    assert b"Topics recorded:" in response.data
    assert b"Size" in response.data
    assert b"Manage" in response.data
    assert b"Rename" in response.data
    assert b"Delete" in response.data
    assert b"recording-manage-button" in response.data


def test_rename_and_delete_recordings(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", "file:recordings_manage_test?mode=memory&cache=shared")
    application = create_app()
    application.config["TESTING"] = True
    client = application.test_client()

    recording_name = f"recording-{uuid4().hex}"
    renamed_name = f"{recording_name}-renamed"
    project_root = Path(__file__).resolve().parent.parent
    recording_path = project_root / "storage" / recording_name
    renamed_path = project_root / "storage" / renamed_name

    shutil.rmtree(recording_path, ignore_errors=True)
    shutil.rmtree(renamed_path, ignore_errors=True)
    recording_path.mkdir(parents=True)
    (recording_path / "metadata.yaml").write_text("topics: []\n")

    try:
        with application.app_context():
            database = get_database()
            database.execute(
                "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
                (f"/storage/{recording_name}", json.dumps(["/ros2log/test/topic"]), "finished"),
            )
            database.commit()
            recording_id = database.execute("SELECT id FROM recordings").fetchone()[0]

        rename_response = client.post(
            f"/api/recordings/{recording_id}/rename",
            json={"name": renamed_name},
        )
        assert rename_response.status_code == 200
        assert renamed_path.exists()

        with application.app_context():
            row = get_database().execute(
                "SELECT output_path FROM recordings WHERE id = ?",
                (recording_id,),
            ).fetchone()
        assert row["output_path"] == f"/storage/{renamed_name}"

        delete_response = client.post(f"/api/recordings/{recording_id}/delete")
        assert delete_response.status_code == 200
        assert not renamed_path.exists()

        with application.app_context():
            count = get_database().execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        assert count == 0
    finally:
        shutil.rmtree(recording_path, ignore_errors=True)
        shutil.rmtree(renamed_path, ignore_errors=True)
