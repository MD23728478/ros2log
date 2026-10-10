import json
import shutil
from html import unescape
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

import pytest

import config
from backend.api import performance
from backend.app import create_app
from runner.client import RunnerMetricsError, _valid_metrics
from runner.metrics import MetricsError, collect_metrics
from runner.server import CommandHandler


def metrics(scope="container"):
    return {
        "scope": scope,
        "hostname": "test-host",
        "cpu_percent": 12.5,
        "memory": {"used_bytes": 25, "total_bytes": 100, "percent": 25.0},
        "storage": {
            "path": "/storage",
            "used_bytes": 50,
            "total_bytes": 100,
            "percent": 50.0,
        },
        "uptime_seconds": 3600.0,
    }


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(
        config, "DATABASE", "file:performance_test?mode=memory&cache=shared"
    )
    application = create_app()
    application.config["TESTING"] = True
    yield application
    application.extensions["database_keeper"].close()


@pytest.mark.parametrize("container", [True, False])
def test_collect_metrics_for_container_and_host(monkeypatch, tmp_path, container):
    monkeypatch.setattr("runner.metrics._is_container", lambda: container)
    monkeypatch.setattr("runner.metrics._memory", lambda value: (25, 100))
    monkeypatch.setattr("runner.metrics._cpu_percent", lambda value, seconds: 12.5)
    monkeypatch.setattr("runner.metrics._uptime", lambda value: 3600.0)
    monkeypatch.setattr(
        "runner.metrics.shutil.disk_usage",
        lambda path: shutil._ntuple_diskusage(100, 50, 50),
    )

    result = collect_metrics(storage_path=tmp_path)

    assert result["scope"] == ("container" if container else "host")
    assert result["cpu_percent"] == 12.5
    assert result["memory"]["percent"] == 25.0
    assert result["storage"]["percent"] == 50.0
    assert result["storage"]["free_bytes"] == 50


def test_collect_metrics_uses_configured_storage_path(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STORAGE_PATH", tmp_path)
    monkeypatch.setattr("runner.metrics._is_container", lambda: False)
    monkeypatch.setattr("runner.metrics._cpu_percent", lambda *args: 0.0)
    monkeypatch.setattr("runner.metrics._memory", lambda *args: (0, 100))
    monkeypatch.setattr("runner.metrics._uptime", lambda *args: 0.0)

    assert collect_metrics()["storage"]["path"] == str(tmp_path)


def test_collect_metrics_marks_unavailable_platform_values(monkeypatch, tmp_path):
    unavailable = lambda *args: (_ for _ in ()).throw(MetricsError("unavailable"))
    monkeypatch.setattr("runner.metrics._is_container", lambda: False)
    monkeypatch.setattr("runner.metrics._cpu_percent", unavailable)
    monkeypatch.setattr("runner.metrics._memory", unavailable)
    monkeypatch.setattr("runner.metrics._uptime", unavailable)
    monkeypatch.setattr(
        "runner.metrics.shutil.disk_usage",
        lambda path: (_ for _ in ()).throw(OSError("missing")),
    )

    result = collect_metrics(storage_path=tmp_path)

    assert result["cpu_percent"] is None
    assert result["memory"] is None
    assert result["storage"] is None
    assert result["uptime_seconds"] is None
    assert _valid_metrics(result)


def test_runner_metrics_endpoint(monkeypatch):
    monkeypatch.setattr("runner.server.collect_metrics", lambda: metrics("host"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), CommandHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/metrics") as response:
            assert json.load(response) == metrics("host")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_production_runner_metrics_use_host_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "RUNNER_STORAGE_PATH", tmp_path / "bags")
    paths = []

    def sample(*, storage_path):
        paths.append(storage_path)
        return metrics("host")

    monkeypatch.setattr("runner.server.collect_metrics", sample)
    server = ThreadingHTTPServer(("127.0.0.1", 0), CommandHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/metrics") as response:
            assert response.status == 200
        assert paths == [tmp_path / "bags"]
        assert (tmp_path / "bags").is_dir()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_performance_api_returns_partial_runner_error(app, monkeypatch):
    monkeypatch.setattr(performance, "collect_metrics", lambda **kwargs: metrics())
    monkeypatch.setattr(
        performance,
        "runner_metrics",
        lambda: (_ for _ in ()).throw(RunnerMetricsError("runner unavailable")),
    )

    response = app.test_client().get("/api/performance")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.get_json()
    assert body["targets"]["application"]["status"] == "ok"
    assert body["targets"]["runner"] == {
        "status": "error",
        "error": "runner unavailable",
    }


def test_performance_api_combines_application_and_runner(app, monkeypatch):
    paths = []

    def sample(*, storage_path):
        paths.append(storage_path)
        return metrics()

    monkeypatch.setattr(performance, "collect_metrics", sample)
    monkeypatch.setattr(performance, "runner_metrics", lambda: metrics("host"))

    response = app.test_client().get("/api/performance")

    assert response.status_code == 200
    body = response.get_json()
    assert body["targets"]["application"]["metrics"]["scope"] == "container"
    assert body["targets"]["runner"]["metrics"]["scope"] == "host"
    assert paths == [Path("/")]


def test_system_page_shows_metrics_and_configuration(app):
    response = app.test_client().get("/system")

    assert response.status_code == 200
    assert b"ros2log Container" in response.data
    assert b"Runner Host" in response.data
    assert b">Poll</button>" in response.data
    assert b"Last: " in response.data
    assert b"Live resource usage" not in response.data
    assert b"Current read-only application configuration" not in response.data
    assert b"PERFORMANCE_POLL_INTERVAL_SECONDS" in response.data
    assert b"ROS2_RUNNER_ADDRESS" in response.data
    assert b'aria-current="page">System' in response.data


def test_system_page_labels_each_storage_path(app, tmp_path):
    app.config["APP_ENV"] = "production"
    app.config["STORAGE_PATH"] = tmp_path / "container"
    app.config["RUNNER_STORAGE_PATH"] = tmp_path / "host"

    page = app.test_client().get("/system").get_data(as_text=True)

    container_card = page.split('data-performance-target="application"', 1)[1].split("</article>", 1)[0]
    runner_card = page.split('data-performance-target="runner"', 1)[1].split("</article>", 1)[0]
    assert 'data-role="storage-path">/</code>' in container_card
    assert f'data-role="storage-path">{tmp_path / "host"}</code>' in runner_card


def test_system_page_shows_all_final_config_values(monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", "file:system_test?mode=memory&cache=shared")
    monkeypatch.setattr(config, "CONDITIONAL_VALUE", "long_value/with-details", raising=False)
    application = create_app()
    application.config["TESTING"] = True

    try:
        page = unescape(application.test_client().get("/system").get_data(as_text=True))
        for key in vars(config):
            if key.isupper():
                assert f"<dt>{key}</dt>" in page
        assert "<dd>long_value/with-details</dd>" in page
        assert "<dd>86400</dd>" in page
        assert "<dt>TESTING</dt>" not in page
    finally:
        application.extensions["database_keeper"].close()
