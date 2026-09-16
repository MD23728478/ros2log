"""Optional browser checks using real dashboard assets and simulated API replies."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

import config
from backend.app import create_app

playwright = pytest.importorskip("playwright.sync_api")
expect = playwright.expect

TEMPERATURE = "/ros2log/test/temperature"
BATTERY = "/ros2log/test/battery"
STATUS = "/ros2log/test/status"


def reading(topic=TEMPERATURE, window=100):
    return {
        "source": "ros2", "topic": topic, "window": window,
        "frequency_hz": 2.5, "bandwidth_bytes_per_second": 1250.5,
    }


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as engine:
        options = {"headless": True}
        if channel := os.environ.get("ROS2LOG_BROWSER_CHANNEL"):
            options["channel"] = channel
        instance = engine.chromium.launch(**options)
        yield instance
        instance.close()


@pytest.fixture
def dashboard(browser, monkeypatch):
    monkeypatch.setattr(config, "PERSIST_DATABASE", False)
    monkeypatch.setattr(config, "DATABASE", f"file:ui_{uuid4().hex}?mode=memory&cache=shared")
    app = create_app()
    client = app.test_client()
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="en-AU")
    page = context.new_page()
    page.set_default_timeout(5000)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    fixture = SimpleNamespace(
        page=page, monitor_requests=[], recording_requests=[],
        topics=[TEMPERATURE, BATTERY, STATUS],
    )

    def route_request(route):
        url = urlsplit(route.request.url)
        if url.path == "/api/topics":
            route.fulfill(json={"topics": fixture.topics})
        elif url.path == "/api/record/status":
            route.fulfill(status=404, json={"error": "No recording"})
        elif url.path == "/api/record/start":
            fixture.recording_requests.append(route.request.post_data_json)
            route.fulfill(json={"state": "completed"})
        elif url.path == "/api/topic-monitor":
            query = parse_qs(url.query)
            fixture.monitor_requests.append(query)
            route.fulfill(json=reading(query["topic"][0], int(query["window"][0])))
        else:
            response = client.get(url.path)
            route.fulfill(status=response.status_code, body=response.data, content_type=response.content_type)

    page.route("**/*", route_request)
    page.goto("http://ros2log.test/")
    expect(page.get_by_role("checkbox", name=TEMPERATURE, exact=True)).to_be_visible()
    yield fixture
    context.close()
    app.extensions["database_keeper"].close()
    assert errors == []


def select(page, topic=TEMPERATURE):
    page.get_by_role("checkbox", name=topic, exact=True).check()


def defer_measurements(page):
    """Keep requests pending so selection changes and long ROS reads are reproducible."""
    page.evaluate("""() => {
      window.pendingMonitorRequests = [];
      const originalFetch = window.fetch;
      window.fetch = (url, options) => {
        if (!String(url).startsWith('/api/topic-monitor?')) return originalFetch(url, options);
        return new Promise(resolve => window.pendingMonitorRequests.push({
          url: String(url),
          reply: (data, status = 200) => resolve(new Response(JSON.stringify(data), {
            status, headers: {'Content-Type': 'application/json'}
          }))
        }));
      };
    }""")


def reply(page, data=None, index=0, status=200):
    page.evaluate("([i, data, status]) => pendingMonitorRequests[i].reply(data, status)",
                  [index, reading() if data is None else data, status])


def pending_count(page):
    return page.evaluate("pendingMonitorRequests.length")


def freeze_clock(page):
    page.clock.install(time=datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc))
    page.clock.pause_at(datetime(2026, 9, 16, 12, 0, 10, tzinfo=timezone.utc))


def test_topic_list_dropdown_and_recording_keep_their_shared_selection(dashboard):
    page = dashboard.page
    expect(page.locator("#topic-monitor-btn")).to_be_disabled()
    expect(page.locator("#topic-monitor-window")).to_be_disabled()
    select(page)
    select(page, BATTERY)
    expect(page.locator("#topic-monitor-selected-count")).to_have_text("2 topics selected.")
    expect(page.locator("#recording-topic")).to_have_text("2 topics selected")
    page.get_by_label("Measure topic").select_option(BATTERY)
    page.get_by_label("Window (messages)").fill("250")
    page.get_by_label("Window (messages)").press("Enter")
    expect(page.locator("#tm-topic")).to_have_text(BATTERY)
    expect(page.locator("#tm-frequency")).to_have_text("2.50")
    expect(page.locator("#tm-bandwidth")).to_have_text("1251")
    expect(page.locator("#tm-window")).to_have_text("250 messages")
    assert dashboard.monitor_requests == [{"topic": [BATTERY], "window": ["250"]}]
    page.locator("#recording-start").click()
    expect(page.locator("#recording-state")).to_have_text("Completed")
    assert dashboard.recording_requests == [{"topics": [TEMPERATURE, BATTERY]}]


@pytest.mark.parametrize("window", ["1", "10001", "2.5", ""])
def test_invalid_window_blocks_manual_and_auto_requests(dashboard, window):
    page = dashboard.page
    select(page)
    page.get_by_label("Window (messages)").fill(window)
    page.locator("#topic-monitor-btn").click()
    page.locator("#topic-monitor-auto").click()
    assert not page.get_by_label("Window (messages)").evaluate("input => input.checkValidity()")
    expect(page.locator("#topic-monitor-auto")).to_have_attribute("aria-pressed", "false")
    assert dashboard.monitor_requests == []


def test_auto_waits_for_completion_and_stop_allows_current_reading_to_finish(dashboard):
    page = dashboard.page
    select(page)
    defer_measurements(page)
    freeze_clock(page)
    page.locator("#topic-monitor-auto").click()
    assert pending_count(page) == 1
    page.clock.fast_forward(15000)
    assert pending_count(page) == 1
    expect(page.locator("#topic-monitor-btn")).to_be_disabled()
    reply(page)
    expect(page.locator("#topic-monitor-state")).to_have_text("Auto on")
    page.clock.fast_forward(2999)
    assert pending_count(page) == 1
    page.clock.fast_forward(1)
    assert pending_count(page) == 2
    page.locator("#topic-monitor-auto").click()
    reply(page, index=1)
    expect(page.locator("#topic-monitor-state")).to_have_text("Updated")
    page.clock.fast_forward(30000)
    assert pending_count(page) == 2
    expect(page.locator("#topic-monitor-auto")).to_have_attribute("aria-pressed", "false")


def test_stop_cancels_scheduled_auto_refresh(dashboard):
    page = dashboard.page
    select(page)
    defer_measurements(page)
    freeze_clock(page)
    page.locator("#topic-monitor-auto").click()
    reply(page)
    expect(page.locator("#topic-monitor-state")).to_have_text("Auto on")
    page.locator("#topic-monitor-auto").click()
    page.clock.fast_forward(10000)
    assert pending_count(page) == 1
    expect(page.locator("#topic-monitor-btn")).to_be_enabled()


@pytest.mark.parametrize("change", ["dropdown", "window", "remove_current", "remove_all"])
def test_changed_settings_ignore_pending_response_and_stop_auto(dashboard, change):
    page = dashboard.page
    select(page)
    if change != "remove_all":
        select(page, BATTERY)
    defer_measurements(page)
    page.locator("#topic-monitor-auto").click()
    if change == "dropdown":
        page.get_by_label("Measure topic").select_option(BATTERY)
    elif change == "window":
        page.get_by_label("Window (messages)").fill("25")
    else:
        page.get_by_role("checkbox", name=TEMPERATURE, exact=True).uncheck()
    expect(page.locator("#topic-monitor-btn")).to_be_disabled()
    expect(page.locator("#topic-monitor-auto")).to_have_attribute("aria-pressed", "false")
    reply(page)
    expect(page.locator("#topic-monitor-result")).to_have_attribute("aria-busy", "false")
    expect(page.locator("#tm-frequency")).to_have_text("\u2014")
    expect(page.locator("#tm-topic")).to_have_text("\u2014")
    if change == "remove_all":
        expect(page.locator("#topic-monitor-input")).to_be_disabled()
        expect(page.locator("#topic-monitor-btn")).to_be_disabled()
    else:
        expected_topic = TEMPERATURE if change == "window" else BATTERY
        expected_window = 25 if change == "window" else 100
        page.locator("#topic-monitor-btn").click()
        query = parse_qs(urlsplit(page.evaluate("pendingMonitorRequests[1].url")).query)
        assert query == {"topic": [expected_topic], "window": [str(expected_window)]}
        reply(page, reading(expected_topic, expected_window), index=1)
        expect(page.locator("#tm-topic")).to_have_text(expected_topic)


def test_list_search_and_other_selections_preserve_active_reading_and_auto(dashboard):
    page = dashboard.page
    select(page)
    defer_measurements(page)
    freeze_clock(page)
    page.locator("#topic-monitor-auto").click()
    select(page, BATTERY)
    expect(page.locator("#topic-monitor-btn")).to_be_disabled()
    reply(page)
    expect(page.locator("#topic-monitor-state")).to_have_text("Auto on")
    page.locator("#topic-list-search").fill("nothing-matches-this")
    expect(page.locator("#topic-monitor-input")).to_have_value(TEMPERATURE)
    expect(page.locator("#tm-frequency")).to_have_text("2.50")
    expect(page.locator("#topic-monitor-auto")).to_have_attribute("aria-pressed", "true")
    page.locator("#topic-list-search").fill("")
    dashboard.topics = [BATTERY, STATUS]
    page.locator("#topic-list-refresh").click()
    expect(page.locator("#topic-monitor-input")).to_have_value(BATTERY)
    expect(page.locator("#tm-frequency")).to_have_text("\u2014")
    expect(page.locator("#topic-monitor-auto")).to_have_attribute("aria-pressed", "false")


@pytest.mark.parametrize("failure", ["http", "incomplete", "network"])
def test_failures_clear_previous_reading_and_stop_auto(dashboard, failure):
    page = dashboard.page
    select(page)
    page.locator("#topic-monitor-btn").click()
    expect(page.locator("#tm-frequency")).to_have_text("2.50")
    if failure == "network":
        page.route("**/api/topic-monitor?**", lambda route: route.abort())
    else:
        defer_measurements(page)
    page.locator("#topic-monitor-auto").click()
    if failure == "http":
        reply(page, {"error": "No measurements received."}, status=504)
    elif failure == "incomplete":
        reply(page, {"topic": TEMPERATURE, "window": 100})
    expect(page.locator("#topic-monitor-state")).to_have_text("Unavailable")
    expect(page.locator("#topic-monitor-error")).to_be_visible()
    expect(page.locator("#tm-frequency")).to_have_text("\u2014")
    expect(page.locator("#topic-monitor-auto")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#topic-monitor-btn")).to_be_enabled()


def test_monitor_controls_fit_a_narrow_dashboard_column(dashboard):
    page = dashboard.page
    page.set_viewport_size({"width": 1024, "height": 1000})
    select(page)
    page.locator("#topic-monitor-btn").click()
    expect(page.locator("#tm-frequency")).to_have_text("2.50")
    bounds = page.locator("#topic-monitor").bounding_box()
    assert bounds is not None
    for selector in ["#topic-monitor-input", "#topic-monitor-window", ".topic-monitor-metric"]:
        for control in page.locator(selector).all():
            box = control.bounding_box()
            assert box["x"] >= bounds["x"]
            assert box["x"] + box["width"] <= bounds["x"] + bounds["width"] + 1
    assert page.locator("#topic-monitor").evaluate("el => el.scrollWidth <= el.clientWidth")
    if artifact_dir := os.environ.get("ROS2LOG_UI_ARTIFACT_DIR"):
        target = Path(artifact_dir)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / "monitor-dashboard-1024.png"), full_page=True)
        page.locator("#topic-monitor").screenshot(path=str(target / "monitor-card.png"))
