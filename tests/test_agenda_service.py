import pytest
from fastapi import HTTPException

from app.agenda_service import AgendaService
from app.calendar_service import CalendarService
from app.task_service import TaskService
from tests.conftest import FakeGoogleClient, FakeTasksClient, make_http_error, raw_task, raw_timed_event


def _service(google_client: FakeGoogleClient, tasks_client: FakeTasksClient) -> AgendaService:
    return AgendaService(CalendarService(google_client), TaskService(tasks_client))


def test_list_agenda_merges_events_and_tasks():
    google = FakeGoogleClient()
    google.queue("list", result={"items": [raw_timed_event("own", start="2026-08-15T10:00:00", end="2026-08-15T11:00:00")]})
    google.queue("list", result={"items": []})  # holiday calendar
    tasks = FakeTasksClient()
    tasks.queue("list", result={"items": [raw_task("task1", due="2026-08-01T00:00:00.000Z")]})
    service = _service(google, tasks)

    agenda = service.list_agenda()

    assert {e.id: (e.is_holiday, e.is_task) for e in agenda} == {
        "own": (False, False),
        "task1": (False, True),
    }
    # merged and sorted chronologically — the task (Aug 1) sorts before the event (Aug 15)
    assert [e.id for e in agenda] == ["task1", "own"]


def test_task_as_event_has_no_start_end_range():
    google = FakeGoogleClient()
    google.queue("list", result={"items": []})
    google.queue("list", result={"items": []})
    tasks = FakeTasksClient()
    tasks.queue("list", result={"items": [raw_task(due="2026-08-15T00:00:00.000Z")]})
    service = _service(google, tasks)

    agenda = service.list_agenda()

    assert agenda[0].start == agenda[0].end
    assert agenda[0].all_day is True


def test_only_holidays_skips_tasks_entirely():
    google = FakeGoogleClient()
    google.queue("list", result={"items": []})  # holiday calendar only
    tasks = FakeTasksClient()  # nothing queued — must never be called
    service = _service(google, tasks)

    agenda = service.list_agenda(only_holidays=True)

    assert agenda == []
    assert tasks.calls == []


def test_task_fetch_failure_does_not_break_the_agenda():
    google = FakeGoogleClient()
    google.queue("list", result={"items": [raw_timed_event()]})
    google.queue("list", result={"items": []})
    tasks = FakeTasksClient()
    tasks.queue("list", error=make_http_error(403))  # e.g. session not yet re-scoped
    service = _service(google, tasks)

    agenda = service.list_agenda()  # must not raise

    assert [e.id for e in agenda] == ["evt1"]


def test_only_tasks_skips_calendar_and_holidays_entirely():
    google = FakeGoogleClient()  # nothing queued — must never be called
    tasks = FakeTasksClient()
    tasks.queue("list", result={"items": [raw_task("task1")]})
    service = _service(google, tasks)

    agenda = service.list_agenda(only_tasks=True)

    assert [e.id for e in agenda] == ["task1"]
    assert google.calls == []


def test_only_tasks_reraises_on_fetch_failure():
    google = FakeGoogleClient()
    tasks = FakeTasksClient()
    tasks.queue("list", error=make_http_error(403))
    service = _service(google, tasks)

    with pytest.raises(HTTPException):
        service.list_agenda(only_tasks=True)


def test_only_holidays_combined_with_only_tasks_is_rejected():
    service = _service(FakeGoogleClient(), FakeTasksClient())

    with pytest.raises(HTTPException) as exc_info:
        service.list_agenda(only_holidays=True, only_tasks=True)

    assert exc_info.value.status_code == 400


def test_list_agenda_forwards_time_bounds_to_tasks():
    import datetime

    google = FakeGoogleClient()
    google.queue("list", result={"items": []})
    google.queue("list", result={"items": []})
    tasks = FakeTasksClient()
    tasks.queue("list", result={"items": []})
    service = _service(google, tasks)
    time_min = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)
    time_max = datetime.datetime(2026, 8, 31, tzinfo=datetime.timezone.utc)

    service.list_agenda(time_min=time_min, time_max=time_max)

    _, kwargs = tasks.calls[0]
    assert kwargs["dueMin"] == time_min.isoformat()
    assert kwargs["dueMax"] == time_max.isoformat()
