from datetime import date

from pydantic import BaseModel


class TaskInput(BaseModel):
    title: str
    notes: str | None = None
    due: date
    completed: bool = False

    def to_google_payload(self) -> dict:
        # Google Tasks has no time-of-day concept at all — "due" is always forced to
        # midnight UTC regardless of what's sent, so there's nothing to lose by always
        # sending midnight ourselves rather than pretending otherwise.
        payload = {
            "title": self.title,
            "due": f"{self.due.isoformat()}T00:00:00.000Z",
            "status": "completed" if self.completed else "needsAction",
        }
        # Same "only send what was actually provided" rule EventInput.to_google_payload
        # follows for description/location: Google's PATCH applies every key it
        # receives literally, including an explicit null — always sending "notes": None
        # on an update that never mentioned notes would silently wipe an existing one.
        if self.notes is not None:
            payload["notes"] = self.notes
        return payload


class Task(BaseModel):
    id: str
    title: str
    notes: str | None = None
    due: date
    status: str  # "needsAction" | "completed" — same convention Event.status uses
