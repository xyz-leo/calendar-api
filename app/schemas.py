from datetime import datetime

from pydantic import BaseModel


class EventInput(BaseModel):
    summary: str
    description: str | None = None
    location: str | None = None
    start: datetime
    end: datetime
    timezone: str = "UTC"

    def to_google_payload(self) -> dict:
        return {
            "summary": self.summary,
            "description": self.description,
            "location": self.location,
            "start": {"dateTime": self.start.isoformat(), "timeZone": self.timezone},
            "end": {"dateTime": self.end.isoformat(), "timeZone": self.timezone},
        }


class Event(BaseModel):
    id: str
    summary: str
    description: str | None = None
    location: str | None = None
    start: datetime
    end: datetime
    timezone: str
    status: str
