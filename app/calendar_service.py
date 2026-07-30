from datetime import date, datetime

from fastapi import Depends, HTTPException
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.google_oauth import get_user_credentials
from app.models import User
from app.schemas import Event, EventInput

CALENDAR_ID = "primary"

# Google's HttpError carries a real, meaningful status — pass the common ones
# through as-is instead of letting every Google hiccup surface as a generic 500.
_STATUS_DETAIL = {
    404: "Event not found",
    403: "Google denied this request (check the granted scope/permissions)",
    401: "Google access expired or was revoked — log in with Google again",
}


def _execute(request):
    try:
        return request.execute()
    except HttpError as e:
        status = e.resp.status
        raise HTTPException(
            status_code=status if status in _STATUS_DETAIL else 502,
            detail=_STATUS_DETAIL.get(status, f"Google Calendar API error ({status})"),
        )


class CalendarService:
    def __init__(self, google_client):
        self.google_client = google_client

    def list_events(self) -> list[Event]:
        raw = _execute(
            self.google_client.events()
            .list(calendarId=CALENDAR_ID, singleEvents=True, orderBy="startTime")
        )
        return [self._normalize(e) for e in raw.get("items", [])]

    def get_event(self, event_id: str) -> Event:
        raw = _execute(
            self.google_client.events().get(calendarId=CALENDAR_ID, eventId=event_id)
        )
        return self._normalize(raw)

    def create_event(self, event: EventInput) -> Event:
        raw = _execute(
            self.google_client.events()
            .insert(calendarId=CALENDAR_ID, body=event.to_google_payload())
        )
        return self._normalize(raw)

    def update_event(self, event_id: str, event: EventInput) -> Event:
        raw = _execute(
            self.google_client.events()
            .patch(calendarId=CALENDAR_ID, eventId=event_id, body=event.to_google_payload())
        )
        return self._normalize(raw)

    def delete_event(self, event_id: str) -> None:
        _execute(
            self.google_client.events().delete(calendarId=CALENDAR_ID, eventId=event_id)
        )

    def _normalize(self, raw: dict) -> Event:
        # All-day events (e.g. birthdays, holidays) are represented by Google with a
        # bare "date" (no time, no timezone — "all day" has no specific hour). Timed
        # events use "dateTime" instead. Both must be handled: a calendar with even
        # one all-day event would otherwise crash every list_events/get_event call.
        start_data = raw["start"]
        end_data = raw["end"]
        all_day = "date" in start_data
        if all_day:
            start = datetime.combine(date.fromisoformat(start_data["date"]), datetime.min.time())
            end = datetime.combine(date.fromisoformat(end_data["date"]), datetime.min.time())
            timezone_name = "UTC"
        else:
            start = start_data["dateTime"]
            end = end_data["dateTime"]
            timezone_name = start_data.get("timeZone", "UTC")

        return Event(
            id=raw["id"],
            summary=raw.get("summary", ""),
            description=raw.get("description"),
            location=raw.get("location"),
            start=start,
            end=end,
            timezone=timezone_name,
            status=raw.get("status", "confirmed"),
            recurrence=raw.get("recurrence"),
            recurring_event_id=raw.get("recurringEventId"),
            all_day=all_day,
        )


def get_calendar_service(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> CalendarService:
    credentials = get_user_credentials(current_user, db)
    google_client = build(
        "calendar", "v3", credentials=credentials, cache_discovery=False
    )
    return CalendarService(google_client)
