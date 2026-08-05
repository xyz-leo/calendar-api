from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from app.agenda_service import AgendaService, get_agenda_service
from app.calendar_service import CalendarService, get_calendar_service
from app.schemas import Event, EventInput
from app.time_range import resolve_time_range

router = APIRouter()


@router.get("/events")
def list_events(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    range_: Literal["today", "week", "month"] | None = Query(None, alias="range"),
    only_holidays: bool = Query(False),
    only_tasks: bool = Query(False),
    service: AgendaService = Depends(get_agenda_service),
) -> list[Event]:
    time_min, time_max = resolve_time_range(from_, to, range_)
    return service.list_agenda(
        time_min=time_min, time_max=time_max, only_holidays=only_holidays, only_tasks=only_tasks
    )


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
