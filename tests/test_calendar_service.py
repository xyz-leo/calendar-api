import pytest
from fastapi import HTTPException

from app.calendar_service import HOLIDAY_CALENDAR_ID, CalendarService
from tests.conftest import FakeGoogleClient, make_http_error, raw_all_day_event, raw_timed_event


def test_list_events_normalizes_timed_event():
    client = FakeGoogleClient()
    client.queue("list", result={"items": [raw_timed_event()]})
    client.queue("list", result={"items": []})  # holiday calendar
    service = CalendarService(client)

    events = service.list_events()

    assert len(events) == 1
    assert events[0].id == "evt1"
    assert events[0].all_day is False
    assert events[0].is_holiday is False
    assert str(events[0].start) == "2026-08-15 10:00:00"


def test_list_events_normalizes_all_day_event():
    client = FakeGoogleClient()
    client.queue("list", result={"items": [raw_all_day_event()]})
    client.queue("list", result={"items": []})  # holiday calendar
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
    client.queue("list", result={"items": []})  # holiday calendar
    service = CalendarService(client)

    events = service.list_events()

    assert [e.id for e in events] == ["a", "b"]
    # second call must have actually used the page token from the first response
    assert client.calls[1][1]["pageToken"] == "page2"


def test_list_events_passes_time_bounds_to_google():
    import datetime

    client = FakeGoogleClient()
    client.queue("list", result={"items": []})
    client.queue("list", result={"items": []})  # holiday calendar
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
    client.queue("list", result={"items": []})  # holiday calendar
    service = CalendarService(client)

    service.list_events()

    _, kwargs = client.calls[0]
    assert "timeMin" not in kwargs
    assert "timeMax" not in kwargs


def test_list_events_merges_and_tags_holiday_calendar():
    client = FakeGoogleClient()
    client.queue("list", result={"items": [raw_timed_event("own", start="2026-08-15T10:00:00", end="2026-08-15T11:00:00")]})
    client.queue("list", result={"items": [raw_all_day_event("holiday1", "Independence Day", start="2026-08-01", end="2026-08-02")]})
    service = CalendarService(client)

    events = service.list_events()

    assert {e.id: e.is_holiday for e in events} == {"own": False, "holiday1": True}
    # merged and sorted chronologically, not just concatenated in fetch order
    assert [e.id for e in events] == ["holiday1", "own"]
    assert client.calls[1][1]["calendarId"] == "en.brazilian#holiday@group.v.calendar.google.com"


def test_list_events_sorts_mixed_aware_and_naive_datetimes():
    # Regression test: a real Google timed event carries an explicit UTC
    # offset (unlike test_list_events_merges_and_tags_holiday_calendar's bare
    # "own" event above, which happens to parse naive and never exercised
    # this) and normalizes to a timezone-aware datetime, while every all-day
    # event (every holiday event) normalizes naive — sorting the merged list
    # used to crash with "can't compare offset-naive and offset-aware
    # datetimes" before _sort_key existed.
    client = FakeGoogleClient()
    client.queue(
        "list",
        result={
            "items": [
                raw_timed_event("timed", start="2026-08-15T10:00:00-03:00", end="2026-08-15T11:00:00-03:00")
            ]
        },
    )
    client.queue("list", result={"items": [raw_all_day_event("holiday1", "Independence Day", start="2026-08-01", end="2026-08-02")]})
    service = CalendarService(client)

    events = service.list_events()  # must not raise TypeError

    assert [e.id for e in events] == ["holiday1", "timed"]


def test_list_events_holiday_fetch_failure_does_not_break_primary_events():
    client = FakeGoogleClient()
    client.queue("list", result={"items": [raw_timed_event()]})
    client.queue("list", error=make_http_error(404))  # holiday calendar unreachable
    service = CalendarService(client)

    events = service.list_events()

    assert [e.id for e in events] == ["evt1"]


def test_list_events_caps_unbounded_holiday_fetch_to_current_year():
    import datetime as dt

    client = FakeGoogleClient()
    client.queue("list", result={"items": []})  # primary
    client.queue("list", result={"items": []})  # holiday
    service = CalendarService(client)

    service.list_events()  # no time_max given — this is the "2029 holidays" bug

    _, holiday_kwargs = client.calls[1]
    assert holiday_kwargs["calendarId"] == HOLIDAY_CALENDAR_ID
    holiday_time_max = dt.datetime.fromisoformat(holiday_kwargs["timeMax"])
    now = dt.datetime.now(dt.timezone.utc)
    assert (holiday_time_max.year, holiday_time_max.month, holiday_time_max.day) == (now.year, 12, 31)


def test_list_events_respects_an_explicit_time_max_for_holidays_too():
    import datetime as dt

    client = FakeGoogleClient()
    client.queue("list", result={"items": []})
    client.queue("list", result={"items": []})
    service = CalendarService(client)
    explicit_max = dt.datetime(2026, 8, 31, 23, 59, 59, tzinfo=dt.timezone.utc)

    service.list_events(time_max=explicit_max)

    _, holiday_kwargs = client.calls[1]
    assert holiday_kwargs["timeMax"] == explicit_max.isoformat()


def test_list_events_only_holidays_skips_the_primary_calendar():
    client = FakeGoogleClient()
    client.queue("list", result={"items": [raw_all_day_event("holiday1")]})
    service = CalendarService(client)

    events = service.list_events(only_holidays=True)

    assert len(client.calls) == 1
    assert client.calls[0][1]["calendarId"] == HOLIDAY_CALENDAR_ID
    assert [e.id for e in events] == ["holiday1"]


def test_list_events_only_holidays_reraises_on_fetch_failure():
    client = FakeGoogleClient()
    client.queue("list", error=make_http_error(404))
    service = CalendarService(client)

    with pytest.raises(HTTPException):
        service.list_events(only_holidays=True)


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
