"""Shared test fixtures.

FakeGoogleClient stands in for the real object googleapiclient's build() returns.
It mimics only the shape CalendarService actually calls:
    google_client.events().list(**kwargs).execute()
    google_client.events().get(**kwargs).execute()
    ...etc

Responses are queued per method name and consumed in order, which is what lets
a test simulate pagination (queue two `list` responses: one with a
nextPageToken, one without) or a Google-side failure (queue an HttpError)
without any real network call or Google account.
"""

import pytest
from googleapiclient.errors import HttpError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.rate_limit import limiter


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # The Limiter's in-memory counters live on one shared instance for the
    # whole process — without this, hitting the same routes across dozens of
    # tests would eventually trip RATE_LIMIT/AUTH_RATE_LIMIT and fail tests
    # that have nothing to do with rate limiting itself.
    limiter.reset()
    yield


@pytest.fixture
def db_session():
    # A fresh, isolated in-memory database per test — never the real
    # data/calendar.db. StaticPool is what makes ":memory:" usable across
    # multiple connections/statements within a single test instead of each
    # connection getting its own separate, empty in-memory database.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


class _FakeResp:
    def __init__(self, status: int):
        self.status = status
        self.reason = "fake reason"  # HttpError.__init__ reads this internally


def make_http_error(status: int) -> HttpError:
    return HttpError(_FakeResp(status), b'{"error": "fake"}', uri="https://fake.invalid")


class _FakeRequest:
    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _FakeEventsResource:
    def __init__(self, client: "FakeGoogleClient"):
        self._client = client

    def _dequeue(self, method: str, kwargs: dict) -> _FakeRequest:
        self._client.calls.append((method, kwargs))
        queue = self._client._queues.get(method)
        if not queue:
            raise AssertionError(f"No queued response for events().{method}({kwargs})")
        return queue.pop(0)

    def list(self, **kwargs):
        return self._dequeue("list", kwargs)

    def get(self, **kwargs):
        return self._dequeue("get", kwargs)

    def insert(self, **kwargs):
        return self._dequeue("insert", kwargs)

    def patch(self, **kwargs):
        return self._dequeue("patch", kwargs)

    def delete(self, **kwargs):
        return self._dequeue("delete", kwargs)


class FakeGoogleClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._queues: dict[str, list[_FakeRequest]] = {}

    def queue(self, method: str, result=None, error: Exception | None = None) -> None:
        self._queues.setdefault(method, []).append(_FakeRequest(result=result, error=error))

    def events(self):
        return _FakeEventsResource(self)


def raw_timed_event(
    event_id: str = "evt1",
    summary: str = "Test event",
    start: str = "2026-08-15T10:00:00",
    end: str = "2026-08-15T11:00:00",
    tz: str = "UTC",
    **extra,
) -> dict:
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start, "timeZone": tz},
        "end": {"dateTime": end, "timeZone": tz},
        "status": "confirmed",
        **extra,
    }


def raw_all_day_event(
    event_id: str = "evt-allday",
    summary: str = "All-day test",
    start: str = "2026-08-15",
    end: str = "2026-08-16",
    **extra,
) -> dict:
    return {
        "id": event_id,
        "summary": summary,
        "start": {"date": start},
        "end": {"date": end},
        "status": "confirmed",
        **extra,
    }
