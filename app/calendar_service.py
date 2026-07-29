from fastapi import Depends
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.google_oauth import get_user_credentials
from app.models import User
from app.schemas import Event, EventInput

CALENDAR_ID = "primary"


class CalendarService:
    def __init__(self, google_client):
        self.google_client = google_client

    def list_events(self) -> list[Event]:
        raw = (
            self.google_client.events()
            .list(calendarId=CALENDAR_ID, singleEvents=True, orderBy="startTime")
            .execute()
        )
        return [self._normalize(e) for e in raw.get("items", [])]

    def get_event(self, event_id: str) -> Event:
        raw = (
            self.google_client.events()
            .get(calendarId=CALENDAR_ID, eventId=event_id)
            .execute()
        )
        return self._normalize(raw)

    def create_event(self, event: EventInput) -> Event:
        raw = (
            self.google_client.events()
            .insert(calendarId=CALENDAR_ID, body=event.to_google_payload())
            .execute()
        )
        return self._normalize(raw)

    def update_event(self, event_id: str, event: EventInput) -> Event:
        raw = (
            self.google_client.events()
            .patch(calendarId=CALENDAR_ID, eventId=event_id, body=event.to_google_payload())
            .execute()
        )
        return self._normalize(raw)

    def delete_event(self, event_id: str) -> None:
        self.google_client.events().delete(
            calendarId=CALENDAR_ID, eventId=event_id
        ).execute()

    def _normalize(self, raw: dict) -> Event:
        return Event(
            id=raw["id"],
            summary=raw.get("summary", ""),
            description=raw.get("description"),
            location=raw.get("location"),
            start=raw["start"]["dateTime"],
            end=raw["end"]["dateTime"],
            timezone=raw["start"].get("timeZone", "UTC"),
            status=raw.get("status", "confirmed"),
        )


def get_calendar_service(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> CalendarService:
    credentials = get_user_credentials(current_user, db)
    google_client = build(
        "calendar", "v3", credentials=credentials, cache_discovery=False
    )
    return CalendarService(google_client)
