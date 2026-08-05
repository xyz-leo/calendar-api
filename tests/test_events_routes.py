import pytest
from fastapi.testclient import TestClient

from app.calendar_service import CalendarService, get_calendar_service
from app.main import app
from app.task_service import TaskService, get_task_service
from tests.conftest import FakeGoogleClient, FakeTasksClient, raw_task, raw_timed_event


class _NoTasksService:
    """Stand-in for TaskService in tests that only care about calendar/holiday
    behavior — GET /events now merges in tasks via AgendaService, so every route
    test needs *some* task_service override or it falls through to the real
    (unauthenticated-in-tests) dependency chain and 401s."""

    def list_tasks(self, **kwargs):
        return []


def _client_with_fake_google(fake_google_client: FakeGoogleClient) -> TestClient:
    app.dependency_overrides[get_calendar_service] = lambda: CalendarService(fake_google_client)
    app.dependency_overrides[get_task_service] = lambda: _NoTasksService()
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_list_events_route_returns_normalized_events():
    fake = FakeGoogleClient()
    fake.queue("list", result={"items": [raw_timed_event(summary="Routed")]})
    fake.queue("list", result={"items": []})  # holiday calendar
    client = _client_with_fake_google(fake)

    response = client.get("/events")

    assert response.status_code == 200
    assert response.json()[0]["summary"] == "Routed"


def test_list_events_route_merges_in_tasks():
    fake_google = FakeGoogleClient()
    fake_google.queue("list", result={"items": [raw_timed_event(summary="An event")]})
    fake_google.queue("list", result={"items": []})  # holiday calendar
    fake_tasks = FakeTasksClient()
    fake_tasks.queue("list", result={"items": [raw_task(title="A task")]})
    app.dependency_overrides[get_calendar_service] = lambda: CalendarService(fake_google)
    app.dependency_overrides[get_task_service] = lambda: TaskService(fake_tasks)
    client = TestClient(app)

    response = client.get("/events")

    assert response.status_code == 200
    by_summary = {e["summary"]: e["is_task"] for e in response.json()}
    assert by_summary == {"An event": False, "A task": True}


def test_list_events_route_only_tasks_skips_calendar_entirely():
    fake_google = FakeGoogleClient()  # nothing queued — must never be called
    fake_tasks = FakeTasksClient()
    fake_tasks.queue("list", result={"items": [raw_task(title="Only this")]})
    app.dependency_overrides[get_calendar_service] = lambda: CalendarService(fake_google)
    app.dependency_overrides[get_task_service] = lambda: TaskService(fake_tasks)
    client = TestClient(app)

    response = client.get("/events", params={"only_tasks": "true"})

    assert response.status_code == 200
    assert [e["summary"] for e in response.json()] == ["Only this"]
    assert fake_google.calls == []


def test_list_events_route_rejects_only_holidays_with_only_tasks():
    client = _client_with_fake_google(FakeGoogleClient())

    response = client.get("/events", params={"only_holidays": "true", "only_tasks": "true"})

    assert response.status_code == 400


def test_list_events_route_range_today_reaches_google_with_time_bounds():
    fake = FakeGoogleClient()
    fake.queue("list", result={"items": []})
    fake.queue("list", result={"items": []})  # holiday calendar
    client = _client_with_fake_google(fake)

    response = client.get("/events", params={"range": "today"})

    assert response.status_code == 200
    _, kwargs = fake.calls[0]
    assert "timeMin" in kwargs and "timeMax" in kwargs


def test_list_events_route_rejects_range_combined_with_from():
    fake = FakeGoogleClient()
    client = _client_with_fake_google(fake)

    response = client.get("/events", params={"range": "today", "from": "2026-08-01"})

    assert response.status_code == 400


def test_list_events_route_rejects_invalid_range_value():
    fake = FakeGoogleClient()
    client = _client_with_fake_google(fake)

    response = client.get("/events", params={"range": "nonsense"})

    assert response.status_code == 422


def test_get_event_route_404_on_missing_event():
    from tests.conftest import make_http_error

    fake = FakeGoogleClient()
    fake.queue("get", error=make_http_error(404))
    client = _client_with_fake_google(fake)

    response = client.get("/events/does-not-exist")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_health_route():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_route_serves_the_web_client():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_auto_generated_docs_are_disabled(path):
    # Security review finding: these were reachable by anyone, unauthenticated — the
    # full API schema plus an interactive "try it out" console, for free. FastAPI's
    # default; explicitly disabled in app/main.py now.
    client = TestClient(app)
    response = client.get(path)
    assert response.status_code == 404


def test_security_headers_are_present():
    # "/" rather than "/health": the latter touches the DB, which fails outside the
    # Docker container in this dev environment (DATABASE_URL points at /app/data) —
    # unrelated to what this test actually checks.
    client = TestClient(app)
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "max-age=" in response.headers["strict-transport-security"]
    assert "default-src 'self'" in response.headers["content-security-policy"]
