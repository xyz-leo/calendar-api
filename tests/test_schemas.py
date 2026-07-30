import pytest
from pydantic import ValidationError

from app.schemas import EventInput


def test_bare_date_is_all_day():
    e = EventInput(summary="x", start="2026-08-15")
    assert e.all_day is True
    assert e.end.isoformat() == "2026-08-16"  # auto-defaulted, exclusive end


def test_full_timestamp_is_timed():
    e = EventInput(summary="x", start="2026-08-15T10:00:00", end="2026-08-15T11:00:00")
    assert e.all_day is False


def test_timestamp_landing_exactly_at_midnight_stays_timed():
    # Regression test: pydantic's lenient date parser used to accept a full
    # timestamp with time "00:00:00" as a bare `date`, silently discarding the
    # time and misclassifying a real timed event (one ending at midnight) as
    # all-day. See app/schemas.py's _classify_date_or_datetime.
    e = EventInput(summary="x", start="2026-07-30T23:30:00", end="2026-07-31T00:00:00")
    assert e.all_day is False
    assert e.end.hour == 0 and e.end.minute == 0


def test_timed_event_without_end_is_rejected():
    with pytest.raises(ValidationError, match="end is required for timed events"):
        EventInput(summary="x", start="2026-08-15T10:00:00")


def test_end_before_start_is_rejected():
    with pytest.raises(ValidationError, match="end must be after start"):
        EventInput(summary="x", start="2026-08-15T10:00:00", end="2026-08-15T09:00:00")


def test_end_equal_to_start_is_rejected():
    with pytest.raises(ValidationError, match="end must be after start"):
        EventInput(summary="x", start="2026-08-15T10:00:00", end="2026-08-15T10:00:00")


def test_mixed_date_and_datetime_is_rejected():
    with pytest.raises(ValidationError, match="not mixed"):
        EventInput(summary="x", start="2026-08-15", end="2026-08-15T10:00:00")


def test_payload_omits_description_and_location_when_not_given():
    # Regression test: to_google_payload() used to always include "description"
    # and "location", even as null, which made Google's PATCH silently WIPE an
    # existing description/location on any update that didn't mention them.
    e = EventInput(summary="x", start="2026-08-15T10:00:00", end="2026-08-15T11:00:00")
    payload = e.to_google_payload()
    assert "description" not in payload
    assert "location" not in payload


def test_payload_includes_description_and_location_when_given():
    e = EventInput(
        summary="x",
        start="2026-08-15T10:00:00",
        end="2026-08-15T11:00:00",
        description="d",
        location="l",
    )
    payload = e.to_google_payload()
    assert payload["description"] == "d"
    assert payload["location"] == "l"


def test_all_day_payload_uses_date_not_datetime_fields():
    e = EventInput(summary="x", start="2026-08-15")
    payload = e.to_google_payload()
    assert payload["start"] == {"date": "2026-08-15"}
    assert payload["end"] == {"date": "2026-08-16"}
    assert "timeZone" not in payload["start"]


def test_timed_payload_includes_timezone():
    e = EventInput(
        summary="x", start="2026-08-15T10:00:00", end="2026-08-15T11:00:00", timezone="America/Sao_Paulo"
    )
    payload = e.to_google_payload()
    assert payload["start"] == {"dateTime": "2026-08-15T10:00:00", "timeZone": "America/Sao_Paulo"}


def test_recurrence_omitted_when_not_given():
    e = EventInput(summary="x", start="2026-08-15T10:00:00", end="2026-08-15T11:00:00")
    assert "recurrence" not in e.to_google_payload()


def test_recurrence_included_when_given():
    e = EventInput(
        summary="x",
        start="2026-08-15T10:00:00",
        end="2026-08-15T11:00:00",
        recurrence=["RRULE:FREQ=WEEKLY;COUNT=5"],
    )
    assert e.to_google_payload()["recurrence"] == ["RRULE:FREQ=WEEKLY;COUNT=5"]
