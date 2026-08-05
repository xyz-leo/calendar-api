# API Reference

Base URL (local): `http://localhost:8088`. All request/response bodies are JSON. All routes
except `/health`, `/`, `/auth/login`, and `/auth/callback` require one of two equivalent proofs of
identity, carrying the exact same JWT:

```
Authorization: Bearer <token>
```

— used by every non-browser client (TUI, `calctl.sh`) — or an HttpOnly `session` cookie, set
automatically by `/auth/callback` for the same-origin web client (`GET /`) and never touched by
that client's own JS. See `docs/architecture.md`'s Session model section for how each is issued.
On `401`, re-authenticate via `/auth/login`.

Every route is rate-limited per client IP — `429` once exceeded. `/auth/login` and
`/auth/callback` use a stricter limit (`AUTH_RATE_LIMIT`, default `10/minute`) than everything else
(`RATE_LIMIT`, default `60/minute`); see `docs/architecture.md`'s "Rate limiting" section for how
to change either via `.env`.

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
| `is_holiday` | boolean | `true` for events merged in from Google's public Brazilian holiday calendar (`GET /events` only — read-only, not creatable/editable/deletable through this API). |
| `is_task` | boolean | `true` for items merged in from Google Tasks (`GET /events` only — see `docs/architecture.md`'s Google Tasks section). A task's `id` is a real Google Tasks id (no prefix/encoding) — it belongs to the `/tasks/*` routes below, not `/events/*`; a client edits/deletes it there, keyed off this flag. |

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

### `Task` (response body)

| Field | Type | Notes |
|---|---|---|
| `id` | string | Google Tasks' own id — a completely different id space than `Event.id`; only ever addressed via `/tasks/*`. |
| `title` | string | |
| `notes` | string \| null | |
| `due` | date | Google Tasks has no time-of-day concept — always a bare date. |
| `status` | string | `"needsAction"` or `"completed"`. |

### `TaskInput` (request body — `POST`/`PATCH /tasks`)

| Field | Type | Required | Notes |
|---|---|---|---|
| `title` | string | yes | |
| `notes` | string \| null | no | Same omission semantics as `EventInput.description`. |
| `due` | date | yes | Bare date only (e.g. `"2026-08-15"`) — a datetime is rejected with `422`, there's no time-of-day field to put it in. |
| `completed` | boolean | no | Default `false`. Maps to Google's `status` (`"completed"` vs `"needsAction"`) — this is how a task is marked done. |

Validation failures return `422`. No `recurrence`/`location`/`timezone` fields exist on this
schema at all — Google Tasks doesn't support any of them, so there's nothing to validate against
or silently ignore.

---

## `GET /events`

List events. Auth required.

**Query parameters** (all optional; `range` cannot be combined with `from`/`to` — `400` if it is;
`only_holidays` and `only_tasks` cannot be combined with each other — `400` if both are `true`):

| Param | Type | Notes |
|---|---|---|
| `from` | date or datetime | Range start. Defaults to now if `to` is given without `from`. Naive values are assumed UTC. |
| `to` | date or datetime | Range end. Unbounded if omitted. |
| `range` | `today` \| `week` \| `month` | Convenience shortcut, always relative to the current time: `today` → end of today, `week` → +7 days, `month` → +30 days. |
| `only_holidays` | boolean | Default `false`. When `true`, skips the primary calendar and tasks entirely and returns only the holiday calendar (still subject to `from`/`to`/`range` above). |
| `only_tasks` | boolean | Default `false`. When `true`, skips the primary calendar and holiday calendar entirely and returns only tasks (still subject to `from`/`to`/`range` above, applied as the tasks' `due` bounds). A fetch failure surfaces as an error here rather than being swallowed, same reasoning as `only_holidays`. |

With no parameters: everything from now onward, unbounded.

**Response**: `200`, `list[Event]`, sorted chronologically. Pagination against Google is handled
internally; the full result set for the requested range is always returned in one response.
Includes events from Google's public Brazilian holiday calendar merged in alongside the account's
own primary-calendar events (`is_holiday: true` on those) — see `docs/architecture.md`. When the
request has no explicit end bound, the holiday side of the fetch is still capped to December 31 of
the current year — an unbounded query would otherwise pull every future instance of a recurring
public calendar (2029, 2030, ... it has no natural end); an explicit `to`/`range` bound is honored
as given instead. A hiccup fetching the holiday calendar is swallowed rather than failing the whole
request, *unless* `only_holidays` is set — there, a fetch failure is the one thing being asked for,
so it surfaces as an error instead of a misleading empty list.

Also includes items from Google Tasks merged in the same way (`is_task: true` on those, see
`docs/architecture.md`'s Google Tasks section) *unless* `only_holidays` is set, in which case tasks
are skipped entirely along with the primary calendar. A hiccup fetching tasks (including a session
that hasn't re-logged-in since the `tasks` scope was added) is swallowed the same way a holiday
fetch hiccup is — the rest of the agenda still comes back — *unless* `only_tasks` is set, in which
case (mirroring `only_holidays`) a fetch failure is the one thing being asked for and surfaces as
an error instead of a misleading empty list.

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

## `GET /tasks`

List tasks from the account's default task list. Auth required. A separate resource from
`/events` — see `docs/architecture.md`'s Google Tasks section for why Tasks isn't just another
`/events` variant.

**Query parameters** (both optional): `from`, `to` — same date/datetime parsing and UTC-assumption
rules as `GET /events`. No `range` shortcut (not needed for the one caller — `AgendaService` —
that uses this internally with its own already-resolved bounds; a human caller can just pass
`from`/`to` directly).

**Response**: `200`, `list[Task]`, unsorted (Google's own list order). Tasks with no `due` date at
all are skipped — see `docs/architecture.md`'s Known limitations. Completed tasks are excluded by
default (Google's own `showCompleted=false` default), matching how Google's own Tasks UI hides
them from the main list.

---

## `GET /tasks/{task_id}`

Fetch one task. Auth required.

**Response**: `200`, `Task`. `404` if the id doesn't exist in the default task list.

---

## `POST /tasks`

Create a task. Auth required.

**Request body**: `TaskInput`.

**Response**: `201`, `Task`.

---

## `PATCH /tasks/{task_id}`

Update a task — including marking it done (`completed: true` in the body). Auth required.

**Request body**: `TaskInput` (the full object, same "resend everything" convention `PATCH
/events/{event_id}` already uses — not a sparse patch).

**Response**: `200`, `Task`. `404` if the id doesn't exist.

---

## `DELETE /tasks/{task_id}`

Delete a task. Auth required.

**Response**: `204`, empty body.

---

## `GET /`

The web client — a single self-contained `app/static/index.html`, same origin as the API. No
auth required to load the page itself (it shows its own login screen if `GET /events` comes back
`401`).

**Response**: `200`, `text/html`.

---

## `GET /auth/login`

Start the Google OAuth flow. No auth required.

**Query parameters**: `port` (optional, `1024`-`65535`). Only meant for a CLI/TUI client that
can't read a cookie the way a browser does — see `/auth/callback` below for what supplying it
changes. The web client never passes this.

**Response**: `307` redirect to Google's consent screen. Sets two short-lived (`max_age=300`)
httponly cookies (`oauth_state`, `oauth_code_verifier`) used by `/auth/callback`, plus a third
(`oauth_loopback_port`) if `port` was given.

---

## `GET /auth/callback`

Google redirects here after consent. Not intended to be called directly. No `Authorization`
header used or required — identity for this request is established via the OAuth `code`
parameter plus the cookies set by `/auth/login`.

**Query parameters**: `code`, `state` (both required, supplied by Google).

**Response**: `307` redirect. Two cases:
- `/auth/login` was called with `port` (the TUI's loopback login): redirects to
  `http://127.0.0.1:<port>/callback?token=<access_token>` — the loopback-listening client
  captures the token from there (see `docs/architecture.md`'s Google OAuth section for why).
- Otherwise (the web client, `GET /`): redirects to `/`, setting the JWT as an HttpOnly, Secure,
  `SameSite=Strict` `session` cookie — the browser carries it automatically on every request to
  this API from then on, no token ever visible to page JS or sitting in a URL.

`400` on state mismatch, missing PKCE verifier, or missing `calendar.events` scope grant.

---

## `POST /auth/logout`

End the current session. Auth required.

**Response**: `200`, `{"detail": string}`. Also clears the `session` cookie, if one was set. See
`docs/architecture.md`'s Session model section for exactly what is and isn't invalidated.

---

## `GET /me`

Current user's identity. Auth required.

**Response**: `200`, `{"id": integer, "email": string}`.

---

## `GET /health`

Liveness check. No auth required. Executes `SELECT 1` against the database.

**Response**: `200`, `{"status": "ok"}`. `500` if the database is unreachable.
