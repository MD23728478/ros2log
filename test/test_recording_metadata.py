import yaml

import config
from backend.api import recording_metadata
from backend.app import create_app
from backend.database import get_database


def test_recording_metadata_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(
        config,
        "DATABASE",
        "file:recording_metadata_test?mode=memory&cache=shared",
    )

    storage = tmp_path / "storage"
    recording_path = storage / "recording-test"
    recording_path.mkdir(parents=True)
    monkeypatch.setattr(recording_metadata, "STORAGE_ROOT", storage)

    metadata = {
        "rosbag2_bagfile_information": {
            "version": 9,
            "storage_identifier": "sqlite3",
            "duration": {"nanoseconds": 4_531_096_768},
            "starting_time": {"nanoseconds_since_epoch": 1_585_866_235_112_411_371},
            "message_count": 10,
            "topics_with_message_count": [
                {
                    "topic_metadata": {
                        "name": "/topic",
                        "type": "std_msgs/msg/String",
                        "serialization_format": "cdr",
                        "offered_qos_profiles": [
                            {
                                "history": "keep_last",
                                "depth": 10,
                                "reliability": "reliable",
                                "durability": "volatile",
                            }
                        ],
                        "type_description_hash": "RIHS01_example",
                    },
                    "message_count": 10,
                }
            ],
            "compression_format": "",
            "compression_mode": "",
            "relative_file_paths": ["recording-test_0.db3"],
            "files": [
                {
                    "path": "recording-test_0.db3",
                    "starting_time": {
                        "nanoseconds_since_epoch": 1_585_866_235_112_411_371
                    },
                    "duration": {"nanoseconds": 4_531_096_768},
                    "message_count": 10,
                }
            ],
            "custom_data": {"robot": "testbot"},
            "ros_distro": "jazzy",
        }
    }
    (recording_path / "metadata.yaml").write_text(
        yaml.safe_dump(metadata), encoding="utf-8"
    )

    application = create_app()
    application.config["TESTING"] = True
    with application.app_context():
        database = get_database()
        database.execute(
            "INSERT INTO recordings (output_path, topics, status) VALUES (?, ?, ?)",
            ("/storage/recording-test", '["/topic"]', "finished"),
        )
        database.commit()
        recording_id = database.execute("SELECT id FROM recordings").fetchone()[0]

    response = application.test_client().get(
        f"/api/recordings/{recording_id}/metadata"
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["recording"] == {
        "id": recording_id,
        "name": "recording-test",
        "status": "finished",
    }
    assert body["summary"] == {
        "started_at": "2020-04-02T22:23:55.112411371Z",
        "duration": {"nanoseconds": "4531096768", "seconds": 4.531096768},
        "message_count": 10,
        "topic_count": 1,
        "ros_distro": "jazzy",
        "storage_identifier": "sqlite3",
        "compression": {"mode": None, "format": None},
    }
    assert body["topics"][0]["name"] == "/topic"
    assert body["topics"][0]["advanced"]["offered_qos_profiles"][0][
        "reliability"
    ] == "reliable"
    assert body["files"][0]["path"] == "recording-test_0.db3"
    assert body["advanced"] == {
        "metadata_version": 9,
        "custom_data": {"robot": "testbot"},
    }
