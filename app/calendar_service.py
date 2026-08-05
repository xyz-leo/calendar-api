from datetime import date, datetime, timezone
from functools import partial

from fastapi import Depends, HTTPException
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.google_api_errors import execute_google_request
from app.google_oauth import get_user_credentials
from app.models import User
from app.schemas import Event, EventInput

_execute = partial(execute_google_request, api_label="Google Calendar API")

CALENDAR_ID = "primary"
# Google's public Brazilian holiday calendar — read-only, merged into list_events
# alongside the user's own events. Not user-configurable yet (see
# docs/architecture.md's Known limitations); events on it are never created,
# updated, or deleted through this API, only ever listed.
HOLIDAY_CALENDAR_ID = "en.brazilian#holiday@group.v.calendar.google.com"


def event_sort_key(event: Event) -> datetime:
    # Timed events normalize to timezone-aware datetimes (Google sends an
    # offset); all-day events (every holiday event, plus any all-day event on
    # the primary calendar) normalize to naive ones (see _normalize below) —
    # Python's datetime comparison refuses to order aware against naive, so
    # sorting the merged list needs a single common representation. Aware
    # values collapse to their UTC-equivalent naive form; naive ones (already
    # implicitly UTC — see all_day's timezone_name="UTC" below) pass through
    # unchanged, landing both kinds on the same absolute timeline.
    start = event.start
    if start.tzinfo is not None:
        return start.astimezone(timezone.utc).replace(tzinfo=None)
    return start


class CalendarService:
    def __init__(self, google_client):
        self.google_client = google_client

    def list_events(
        self,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        *,
        only_holidays: bool = False,
    ) -> list[Event]:
        # An unbounded time_max would otherwise pull every future instance of a
        # recurring public holiday calendar (2029, 2030, ... — it has no natural
        # end), which is never what "everything upcoming" should mean for
        # holidays specifically. Only kicks in when the caller didn't already
        # supply their own end bound (an explicit from/to/range filter is
        # respected as-is, same as for the primary calendar).
        holiday_time_max = time_max
        if holiday_time_max is None:
            now = datetime.now(timezone.utc)
            holiday_time_max = datetime(now.year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        events: list[Event] = []
        if not only_holidays:
            events = self._list_from_calendar(CALENDAR_ID, time_min, time_max, is_holiday=False)
        try:
            events.extend(
                self._list_from_calendar(HOLIDAY_CALENDAR_ID, time_min, holiday_time_max, is_holiday=True)
            )
        except HTTPException:
            # Normally the holiday calendar is a nice-to-have merged on top of the
            # user's own events — a hiccup fetching it (Google outage, calendar
            # briefly unreachable) shouldn't take down the primary event list with
            # it. But if holidays are literally the only thing being asked for,
            # silently returning an empty list would misrepresent "couldn't fetch
            # holidays" as "no holidays" — let it surface instead.
            if only_holidays:
                raise
        events.sort(key=event_sort_key)
        return events

    def _list_from_calendar(
        self,
        calendar_id: str,
        time_min: datetime | None,
        time_max: datetime | None,
        *,
        is_holiday: bool,
    ) -> list[Event]:
        params = {"calendarId": calendar_id, "singleEvents": True, "orderBy": "startTime"}
        if time_min is not None:
            params["timeMin"] = time_min.isoformat()
        if time_max is not None:
            params["timeMax"] = time_max.isoformat()

        events: list[Event] = []
        page_token = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            raw = _execute(
                self.google_client.events().list(**params), not_found_detail="Event not found"
            )
            events.extend(self._normalize(e, is_holiday=is_holiday) for e in raw.get("items", []))
            page_token = raw.get("nextPageToken")
            if not page_token:
                break
        return events

    def get_event(self, event_id: str) -> Event:
        raw = _execute(
            self.google_client.events().get(calendarId=CALENDAR_ID, eventId=event_id),
            not_found_detail="Event not found",
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
            .patch(calendarId=CALENDAR_ID, eventId=event_id, body=event.to_google_payload()),
            not_found_detail="Event not found",
        )
        return self._normalize(raw)

    def delete_event(self, event_id: str) -> None:
        _execute(
            self.google_client.events().delete(calendarId=CALENDAR_ID, eventId=event_id),
            not_found_detail="Event not found",
        )

    def _normalize(self, raw: dict, *, is_holiday: bool = False) -> Event:
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
            is_holiday=is_holiday,
        )


def get_calendar_service(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> CalendarService:
    credentials = get_user_credentials(current_user, db)
    google_client = build(
        "calendar", "v3", credentials=credentials, cache_discovery=False
    )
    return CalendarService(google_client)
