from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

# "range" is a convenience so a client never has to compute dates itself for the
# common cases — each window always starts from now, only the end differs.
_RANGE_END = {
    "today": lambda now: now.replace(hour=23, minute=59, second=59, microsecond=999999),
    "week": lambda now: now + timedelta(days=7),
    "month": lambda now: now + timedelta(days=30),
}


def _ensure_utc(dt: datetime) -> datetime:
    # A "from"/"to" query value with no offset (e.g. "2026-08-15T10:00:00") parses
    # as naive — Google's API requires an explicit offset, so assume UTC rather
    # than reject it (same convention EventInput already uses for start/end).
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def resolve_time_range(
    from_: datetime | None, to: datetime | None, range_: str | None
) -> tuple[datetime, datetime | None]:
    now = datetime.now(timezone.utc)

    if range_ is not None:
        if from_ is not None or to is not None:
            raise HTTPException(status_code=400, detail="Cannot combine 'range' with 'from'/'to'")
        return now, _RANGE_END[range_](now)

    if from_ is not None or to is not None:
        time_min = _ensure_utc(from_) if from_ is not None else now
        time_max = _ensure_utc(to) if to is not None else None
        return time_min, time_max

    # Default: everything upcoming, no end cutoff.
    return now, None
