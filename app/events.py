from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.calendar_service import CalendarService, get_calendar_service
from app.schemas import Event, EventInput

router = APIRouter()

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


def _resolve_time_range(
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


@router.get("/events")
def list_events(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    range_: Literal["today", "week", "month"] | None = Query(None, alias="range"),
    service: CalendarService = Depends(get_calendar_service),
) -> list[Event]:
    time_min, time_max = _resolve_time_range(from_, to, range_)
    return service.list_events(time_min=time_min, time_max=time_max)


@router.get("/events/{event_id}")
def get_event(
    event_id: str, service: CalendarService = Depends(get_calendar_service)
) -> Event:
    return service.get_event(event_id)


@router.post("/events", status_code=201)
def create_event(
    event: EventInput, service: CalendarService = Depends(get_calendar_service)
) -> Event:
    return service.create_event(event)


@router.patch("/events/{event_id}")
def update_event(
    event_id: str,
    event: EventInput,
    service: CalendarService = Depends(get_calendar_service),
) -> Event:
    return service.update_event(event_id, event)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(
    event_id: str, service: CalendarService = Depends(get_calendar_service)
) -> Response:
    service.delete_event(event_id)
    return Response(status_code=204)
