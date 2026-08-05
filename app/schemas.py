from datetime import date, datetime, timedelta

from pydantic import BaseModel, field_validator, model_validator


def _classify_date_or_datetime(value):
    # Explicit, not left to pydantic's own date|datetime union resolution: that
    # was found to lenient-parse a full timestamp landing exactly at midnight
    # (e.g. "2026-07-31T00:00:00") as a bare `date`, silently discarding the time
    # and misclassifying a real timed event (one ending at midnight — a normal
    # thing to want) as all-day. Deciding explicitly from the presence of a time
    # separator, before pydantic ever sees the string, removes the ambiguity.
    if isinstance(value, str):
        if "T" in value or " " in value.strip():
            return datetime.fromisoformat(value)
        return date.fromisoformat(value)
    return value


class EventInput(BaseModel):
    summary: str
    description: str | None = None
    location: str | None = None
    # Accepting date as well as datetime is what makes all-day events possible: a
    # bare date (e.g. "2026-08-15") means all-day, a full timestamp means timed.
    # See _classify_date_or_datetime above for how that's actually decided.
    start: date | datetime
    # Optional: for an all-day event, Google requires end = start + 1 day for a
    # single day (its "end" is exclusive) — that's an implementation detail of
    # Google's API, not something a caller should have to know or restate. If end
    # is omitted for an all-day start, _validate_end fills it in automatically.
    # Timed events still require an explicit end (a duration isn't derivable).
    end: date | datetime | None = None
    timezone: str = "UTC"
    recurrence: list[str] | None = None

    @field_validator("start", "end", mode="before")
    @classmethod
    def _parse_start_end(cls, value):
        return _classify_date_or_datetime(value)

    @model_validator(mode="after")
    def _validate_end(self) -> "EventInput":
        if self.end is None:
            if isinstance(self.start, datetime):
                raise ValueError("end is required for timed events (only all-day events can omit it)")
            self.end = self.start + timedelta(days=1)
        elif isinstance(self.start, datetime) != isinstance(self.end, datetime):
            raise ValueError("start and end must both be dates (all-day) or both be datetimes (timed), not mixed")

        if self.end <= self.start:
            raise ValueError("end must be after start")
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
            "start": start_field,
            "end": end_field,
        }
        # description/location/recurrence are only included when actually provided —
        # Google's PATCH applies each key it receives literally, including an explicit
        # null. Always sending "description": None on an update that never mentioned
        # description would silently WIPE an existing description on Google's side.
        if self.description is not None:
            payload["description"] = self.description
        if self.location is not None:
            payload["location"] = self.location
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
    is_holiday: bool = False
    is_task: bool = False
