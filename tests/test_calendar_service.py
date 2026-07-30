import pytest
from fastapi import HTTPException

from app.calendar_service import CalendarService
from tests.conftest import FakeGoogleClient, make_http_error, raw_all_day_event, raw_timed_event


def test_list_events_normalizes_timed_event():
    client = FakeGoogleClient()
    client.queue("list", result={"items": [raw_timed_event()]})
    service = CalendarService(client)

    events = service.list_events()

    assert len(events) == 1
    assert events[0].id == "evt1"
    assert events[0].all_day is False
    assert str(events[0].start) == "2026-08-15 10:00:00"


def test_list_events_normalizes_all_day_event():
    client = FakeGoogleClient()
    client.queue("list", result={"items": [raw_all_day_event()]})
    service = CalendarService(client)

    events = service.list_events()

    assert events[0].all_day is True
    assert events[0].timezone == "UTC"
    # end is exclusive on Google's side — the day AFTER the last day
    assert str(events[0].end) == "2026-08-16 00:00:00"


def test_list_events_follows_pagination():
    client = FakeGoogleClient()
    client.queue("list", result={"items": [raw_timed_event("a")], "nextPageToken": "page2"})
    client.queue("list", result={"items": [raw_timed_event("b")]})
    service = CalendarService(client)

    events = service.list_events()

    assert [e.id for e in events] == ["a", "b"]
    # second call must have actually used the page token from the first response
    assert client.calls[1][1]["pageToken"] == "page2"


def test_list_events_passes_time_bounds_to_google():
    import datetime

    client = FakeGoogleClient()
    client.queue("list", result={"items": []})
    service = CalendarService(client)
    time_min = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc)
    time_max = datetime.datetime(2026, 8, 31, tzinfo=datetime.timezone.utc)

    service.list_events(time_min=time_min, time_max=time_max)

    method, kwargs = client.calls[0]
    assert method == "list"
    assert kwargs["timeMin"] == time_min.isoformat()
    assert kwargs["timeMax"] == time_max.isoformat()


def test_list_events_omits_bounds_when_not_given():
    client = FakeGoogleClient()
    client.queue("list", result={"items": []})
    service = CalendarService(client)

    service.list_events()

    _, kwargs = client.calls[0]
    assert "timeMin" not in kwargs
    assert "timeMax" not in kwargs


def test_get_event_normalizes():
    client = FakeGoogleClient()
    client.queue("get", result=raw_timed_event(summary="Fetched"))
    service = CalendarService(client)

    event = service.get_event("evt1")

    assert event.summary == "Fetched"


def test_create_event_sends_payload_and_normalizes_response():
    from app.schemas import EventInput

    client = FakeGoogleClient()
    client.queue("insert", result=raw_timed_event(summary="Created"))
    service = CalendarService(client)
    event_in = EventInput(
        summary="Created", start="2026-08-15T10:00:00", end="2026-08-15T11:00:00"
    )

    result = service.create_event(event_in)

    assert result.summary == "Created"
    _, kwargs = client.calls[0]
    assert kwargs["body"]["summary"] == "Created"


def test_create_event_passes_recurrence_through():
    from app.schemas import EventInput

    client = FakeGoogleClient()
    client.queue("insert", result=raw_timed_event())
    service = CalendarService(client)
    event_in = EventInput(
        summary="Standup",
        start="2026-08-03T09:00:00",
        end="2026-08-03T09:15:00",
        recurrence=["RRULE:FREQ=WEEKLY;COUNT=10"],
    )

    service.create_event(event_in)

    _, kwargs = client.calls[0]
    assert kwargs["body"]["recurrence"] == ["RRULE:FREQ=WEEKLY;COUNT=10"]


def test_delete_event_calls_google_with_right_id():
    client = FakeGoogleClient()
    client.queue("delete", result=None)
    service = CalendarService(client)

    service.delete_event("evt1")

    method, kwargs = client.calls[0]
    assert method == "delete"
    assert kwargs["eventId"] == "evt1"


@pytest.mark.parametrize(
    ("status", "expected_status", "expected_detail_snippet"),
    [
        (404, 404, "not found"),
        (403, 403, "denied"),
        (401, 401, "expired or was revoked"),
        (500, 502, "Google Calendar API error"),
    ],
)
def test_google_errors_translate_to_clean_http_exceptions(
    status, expected_status, expected_detail_snippet
):
    client = FakeGoogleClient()
    client.queue("get", error=make_http_error(status))
    service = CalendarService(client)

    with pytest.raises(HTTPException) as exc_info:
        service.get_event("missing")

    assert exc_info.value.status_code == expected_status
    assert expected_detail_snippet.lower() in exc_info.value.detail.lower()
