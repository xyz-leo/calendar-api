from fastapi import APIRouter, Depends, Response

from app.calendar_service import CalendarService, get_calendar_service
from app.schemas import Event, EventInput

router = APIRouter()


@router.get("/events")
def list_events(service: CalendarService = Depends(get_calendar_service)) -> list[Event]:
    return service.list_events()


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
