# API Reference

Base URL (local): `http://localhost:8088`. All request/response bodies are JSON. All routes
except `/health`, `/auth/login`, and `/auth/callback` require:

```
Authorization: Bearer <token>
```

where `<token>` is the JWT returned by `/auth/callback`. See `docs/architecture.md` for the
session model. On `401`, re-authenticate via `/auth/login`.

---

## Schemas

### `Event` (response body)

| Field | Type | Notes |
|---|---|---|
| `id` | string | Google's event id. |
| `summary` | string | |
| `description` | string \| null | |
| `location` | string \| null | |
| `start` | datetime (ISO 8601) | Always a full datetime, even for all-day events (midnight). |
| `end` | datetime (ISO 8601) | Exclusive for all-day events (see `all_day`). |
| `timezone` | string | IANA name, or `"UTC"` for all-day events. |
| `status` | string | Google's event status, e.g. `"confirmed"`, `"cancelled"`. |
| `recurrence` | array[string] \| null | RFC 5545 rules; see `docs/rfc5545.md`. |
| `recurring_event_id` | string \| null | Set on an expanded occurrence; points to the series. |
| `all_day` | boolean | |

### `EventInput` (request body — `POST`/`PATCH /events`)

| Field | Type | Required | Notes |
|---|---|---|---|
| `summary` | string | yes | |
| `description` | string \| null | no | Omit to leave unchanged on update; omitted keys are never sent to Google, so an existing value is never clobbered. |
| `location` | string \| null | no | Same omission semantics as `description`. |
| `start` | date or datetime | yes | A bare date (`"2026-08-15"`) creates an all-day event; a full timestamp (`"2026-08-15T14:00:00"`) creates a timed event. |
| `end` | date or datetime | conditional | Required for timed events. Optional for all-day events — defaults to `start + 1 day` (Google's all-day `end` is exclusive). Must be the same kind (date/datetime) as `start`, and strictly after it. |
| `timezone` | string | no | Default `"UTC"`. Ignored for all-day events. |
| `recurrence` | array[string] | no | A single RFC 5545 `RRULE` string per entry. |

Validation failures return `422` with a Pydantic-generated error body.

---

## `GET /events`

List events. Auth required.

**Query parameters** (all optional; `range` cannot be combined with `from`/`to` — `400` if it is):

| Param | Type | Notes |
|---|---|---|
| `from` | date or datetime | Range start. Defaults to now if `to` is given without `from`. Naive values are assumed UTC. |
| `to` | date or datetime | Range end. Unbounded if omitted. |
| `range` | `today` \| `week` \| `month` | Convenience shortcut, always relative to the current time: `today` → end of today, `week` → +7 days, `month` → +30 days. |

With no parameters: everything from now onward, unbounded.

**Response**: `200`, `list[Event]`. Pagination against Google is handled internally; the full
result set for the requested range is always returned in one response.

---

## `GET /events/{event_id}`

Fetch one event. Auth required.

**Response**: `200`, `Event`. `404` if the id doesn't exist on the account's primary calendar
(the only calendar this API operates against — see `docs/architecture.md`).

---

## `POST /events`

Create an event. Auth required.

**Request body**: `EventInput`.

**Response**: `201`, `Event` (the event as Google actually stored it, not an echo of the request).

---

## `PATCH /events/{event_id}`

Update an event. Auth required. Partial update: only fields present in `EventInput` beyond the
always-required `summary`/`start` are sent to Google.

**Request body**: `EventInput`. Note: switching an existing event between all-day and timed is
not supported — see `docs/architecture.md`'s Known Limitations.

**Response**: `200`, `Event`. `404` if the id doesn't exist.

---

## `DELETE /events/{event_id}`

Delete an event. Auth required.

**Response**: `204`, empty body. Note: Google retains a cancelled-status tombstone record
internally; a subsequent `GET` on the same id may still return `200` with `"status": "cancelled"`
rather than `404`, briefly.

---

## `GET /auth/login`

Start the Google OAuth flow. No auth required.

**Query parameters**: `port` (optional, `1024`-`65535`). Only meant for a CLI/TUI client that
can't read the JSON response `/auth/callback` normally returns — see that endpoint below for
what supplying it changes.

**Response**: `307` redirect to Google's consent screen. Sets two short-lived (`max_age=300`)
httponly cookies (`oauth_state`, `oauth_code_verifier`) used by `/auth/callback`, plus a third
(`oauth_loopback_port`) if `port` was given.

---

## `GET /auth/callback`

Google redirects here after consent. Not intended to be called directly. No `Authorization`
header used or required — identity for this request is established via the OAuth `code`
parameter plus the cookies set by `/auth/login`.

**Query parameters**: `code`, `state` (both required, supplied by Google).

**Response**: `200`, `{"access_token": string, "token_type": "bearer"}` — unless `/auth/login`
was called with `port`, in which case this is instead a `307` redirect to
`http://127.0.0.1:<port>/callback?token=<access_token>` (the loopback-listening client captures
it from there; see `docs/architecture.md`'s Google OAuth section for why). `400` on state
mismatch, missing PKCE verifier, or missing `calendar.events` scope grant.

---

## `POST /auth/logout`

End the current session. Auth required.

**Response**: `200`, `{"detail": string}`. See `docs/architecture.md`'s Session model section for
exactly what is and isn't invalidated.

---

## `GET /me`

Current user's identity. Auth required.

**Response**: `200`, `{"id": integer, "email": string}`.

---

## `GET /health`

Liveness check. No auth required. Executes `SELECT 1` against the database.

**Response**: `200`, `{"status": "ok"}`. `500` if the database is unreachable.
