from datetime import date, datetime, timedelta

from pydantic import BaseModel, model_validator


class EventInput(BaseModel):
    summary: str
    description: str | None = None
    location: str | None = None
    # Accepting date as well as datetime is what makes all-day events possible:
    # pydantic only matches the `date` branch when the input has no time component
    # at all (e.g. "2026-08-15") — a full timestamp always matches `datetime`
    # instead. So "did the caller pass a bare date?" and "is this all-day?" are
    # the same question, with no separate flag needed.
    start: date | datetime
    # Optional: for an all-day event, Google requires end = start + 1 day for a
    # single day (its "end" is exclusive) — that's an implementation detail of
    # Google's API, not something a caller should have to know or restate. If end
    # is omitted for an all-day start, _default_end fills it in automatically.
    # Timed events still require an explicit end (a duration isn't derivable).
    end: date | datetime | None = None
    timezone: str = "UTC"
    recurrence: list[str] | None = None

    @model_validator(mode="after")
    def _default_end(self) -> "EventInput":
        if self.end is None:
            if isinstance(self.start, datetime):
                raise ValueError("end is required for timed events (only all-day events can omit it)")
            self.end = self.start + timedelta(days=1)
        return self

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)

    def to_google_payload(self) -> dict:
        if self.all_day:
            # Google's all-day format: bare "date" strings, no "dateTime"/"timeZone"
            # at all — a day has no timezone. Note Google's end.date is EXCLUSIVE
            # (the day after the last day), same as Python's usual [start, end) ranges.
            start_field = {"date": self.start.isoformat()}
            end_field = {"date": self.end.isoformat()}
        else:
            start_field = {"dateTime": self.start.isoformat(), "timeZone": self.timezone}
            end_field = {"dateTime": self.end.isoformat(), "timeZone": self.timezone}

        payload = {
            "summary": self.summary,
            "description": self.description,
            "location": self.location,
            "start": start_field,
            "end": end_field,
        }
        if self.recurrence:
            payload["recurrence"] = self.recurrence
        return payload


class Event(BaseModel):
    id: str
    summary: str
    description: str | None = None
    location: str | None = None
    start: datetime
    end: datetime
    timezone: str
    status: str
    recurrence: list[str] | None = None
    recurring_event_id: str | None = None
    all_day: bool = False
