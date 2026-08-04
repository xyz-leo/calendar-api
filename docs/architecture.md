# Architecture

## Overview

calendar-api is a backend service that owns the relationship with Google Calendar. Clients never
hold a Google credential or see a Google response shape directly; they authenticate against this
API and interact with a normalized `Event` representation.

All writes (create/update/delete) and single-event lookups act on the authenticated user's
**primary calendar only** (`CalendarService.CALENDAR_ID = "primary"`). `list_events` is the one
exception: it also merges in read-only events from Google's public Brazilian holiday calendar
(`CalendarService.HOLIDAY_CALENDAR_ID`), tagging each with `is_holiday: true` on the `Event`
response — there is otherwise no general multi-calendar support (see
[Known limitations](#known-limitations)).

```
Client (web / TUI / CLI)
    │  JSON over HTTP, Authorization: Bearer <JWT> or a "session" cookie (web client only)
    ▼
API layer            app/auth.py, app/events.py
    │
    ▼
Service layer         app/calendar_service.py
    │  authenticated googleapiclient calls
    ▼
Google Calendar API
```

The API layer owns HTTP concerns (routing, query/body parsing, status codes). The service layer
owns all Google Calendar API interaction and is deliberately free of any FastAPI dependency,
constructed with an injected client object (`CalendarService(google_client)`) rather than building
its own connection — this is what makes it unit-testable without network access (see
`tests/conftest.py`'s `FakeGoogleClient` and the "Development, testing, and CI" section below).

## Module responsibilities

| Module | Responsibility |
|---|---|
| `app/config.py` | Typed settings loaded from environment variables. Fails fast at import time if any required value is missing. |
| `app/database.py` | SQLAlchemy engine/session setup; `get_db` FastAPI dependency. |
| `app/models.py` | ORM models. Currently one table: `users`. |
| `app/security.py` | JWT signing/verification (`create_access_token`, `decode_access_token`) and Fernet encryption of stored Google refresh tokens. |
| `app/google_oauth.py` | Google OAuth `Flow` construction, scope list, and `get_user_credentials` (decrypt + silently refresh a per-user Google credential). |
| `app/auth.py` | `/auth/*` and `/me` routes; `get_current_user` (the auth dependency every protected route uses). |
| `app/schemas.py` | Pydantic request/response models (`EventInput`, `Event`) and all input validation. |
| `app/calendar_service.py` | `CalendarService` — all Google Calendar API calls, response normalization, error translation. `get_calendar_service` FastAPI dependency wires it to a real, authenticated client. |
| `app/events.py` | `/events` routes; time-range query parameter resolution. |
| `app/main.py` | FastAPI app construction, router registration, startup (table creation), `/health`, `GET /` (serves the web client). |
| `app/static/index.html` | The web client — single self-contained HTML/CSS/JS file, same origin as the API. Not a Python module; see "Clients" below. |
| `scripts/calctl.sh` | Reference CLI client; not part of the API itself. |

## Data model

Single table, `users`:

| Column | Type | Notes |
|---|---|---|
| `id` | integer, PK | Auto-assigned. |
| `google_id` | string, unique, indexed | Google's stable account identifier (`id_token`'s `sub` claim). Lookup key for login — never `email`. |
| `email` | string | Updated on every login. |
| `encrypted_refresh_token` | string | Fernet-encrypted Google OAuth refresh token. Empty string means no usable Google credential (post-logout, or never-refreshed new row). |
| `access_token` | string | Current Google OAuth access token, plaintext (short-lived, ~1h). |
| `access_token_expires_at` | datetime | Naive UTC. Used by `get_user_credentials` to decide whether a refresh is needed. |
| `created_at` | datetime | Set once, at row creation. |
| `session_version` | integer, default 0 | Incremented on logout; see [Session model](#session-model). |

Schema changes are currently applied manually (`Base.metadata.create_all` only creates missing
tables, it does not alter existing ones — no migration tool is wired up; see
[Known limitations](#known-limitations)).

## Authentication and session model

Two independent credential systems exist; neither implies the other.

### Google OAuth

Standard Authorization Code flow with PKCE, implemented in `app/google_oauth.py` /
`app/auth.py`'s `login`/`callback` routes.

- Scopes requested: `openid`, `.../auth/userinfo.email`, `.../auth/calendar.events`.
- `access_type=offline` + `prompt=consent` on every login, to guarantee a refresh token is
  reissued each time.
- `id_token` signature is verified (`google_id_token.verify_oauth2_token`) before any claim is
  trusted.
- Google's `access_token`/`refresh_token` are stored on the `User` row (refresh token encrypted).
  `get_user_credentials` transparently refreshes an expired access token before every
  `CalendarService` call; callers never see this.

`/auth/callback` hands the minted JWT back one of two ways, depending on who asked:

- **The web client** (`app/static/index.html`, served at `GET /` — same origin as this API):
  the default case. Redirects to `/`, setting the JWT as an `HttpOnly`, `Secure`,
  `SameSite=Strict` `session` cookie. The token never touches the URL, a response body, or any
  JS-readable storage — the browser just attaches the cookie automatically on every later
  request. `HttpOnly` means an XSS bug in the page can't read the token itself and walk away
  with it (it can still ride the session while its script is running, same as any XSS — see
  below); `SameSite=Strict` is what makes that safe against CSRF (the cookie is never attached to
  a request that didn't originate from this same site). No CORS is involved anywhere in this —
  it's same-origin by construction, not cross-origin with an allowlist.
- **A CLI/TUI client** (no way to receive a cookie or read a response body itself): `/auth/login`
  accepts an optional `port` query param; `/auth/callback` then redirects the browser a *second*
  time, to `http://127.0.0.1:<port>/callback?token=<jwt>`, instead of setting a cookie. This is
  RFC 8252's "loopback interface redirection" pattern for native/CLI apps (the same approach
  `gcloud`/`gh` use) — the client starts a temporary local HTTP server on that port before opening
  the browser, and captures the token from the redirect itself, no copy-paste involved. The token
  does end up briefly in a URL's query string, but only a `127.0.0.1`-only one: it never leaves
  the machine, unlike a token in a URL that could cross the network or land in a shared proxy/
  server log.

Google's own registered redirect URI never changes either way (`build_flow()` always uses the
single fixed `GOOGLE_REDIRECT_URI`) — both hops above happen entirely between this API and the
client (browser or loopback listener), both already under the same trust boundary.

`get_current_user` (`app/auth.py`) accepts the JWT from either transport — an `Authorization:
Bearer <token>` header (TUI, `calctl.sh`, any non-browser client) or the `session` cookie (the web
client) — validating the exact same token the same way regardless of which one carried it.

### Application session

Stateless JWT (`HS256`), issued by `/auth/callback`, required on every protected route as either
an `Authorization: Bearer <token>` header or a `session` cookie (see the Google OAuth section
above for which clients get which). Payload: `{"sub": <user_id>, "sv": <session_version>, "exp":
...}`,
7-day lifetime (`app/security.py`'s `JWT_LIFETIME`) — matches how long Google itself keeps a
refresh token alive while this app's OAuth consent screen is in Testing status.

`get_current_user` (`app/auth.py`) validates, in order: signature + expiry (via `pyjwt`), that the
referenced user still exists, and that the token's `sv` claim matches the user's *current*
`session_version`. The last check is what makes logout meaningful despite the token being
otherwise stateless — see below.

### Logout

`POST /auth/logout`: increments `session_version` (invalidates every previously-issued token for
that user, immediately, across all routes) and clears `encrypted_refresh_token`/`access_token`
(breaks Google access until a fresh login). **This does not call Google's token revocation
endpoint** — the app-side grant is discarded, but Google's own record of the authorization is
untouched. A subsequent login re-runs the full consent screen and obtains a fresh refresh token,
which is sufficient for "must log in again" but is not equivalent to revoking the app's access
from the user's Google account.

## Error handling

| Source | Mapping |
|---|---|
| Pydantic validation (query params, request bodies) | `422`, automatic |
| Missing/invalid/expired JWT | `401` (`get_current_user`) |
| JWT `sv` mismatch (logged out) | `401`, `"Session has been logged out"` |
| No/invalid stored Google refresh token | `401`, `"Google access expired or was revoked — log in with Google again."` (`get_user_credentials`) |
| Google refresh token rejected by Google (`RefreshError`) | same as above |
| Google API `HttpError` | passed through for `404`/`403`/`401` with a clean message; anything else becomes `502` (`CalendarService._execute`) |
| `range` combined with `from`/`to` on `GET /events` | `400` |
| Rate limit exceeded (see below) | `429` |

## Rate limiting

`app/rate_limit.py` defines one shared [slowapi](https://github.com/laurentS/slowapi) `Limiter`,
keyed by client IP (`slowapi.util.get_remote_address`), with in-memory counters — fine for this
app's single-container deployment, but note that counters reset on restart and wouldn't be shared
across multiple replicas if this were ever scaled horizontally.

- `RATE_LIMIT` (`Settings.rate_limit`, default `"60/minute"`) is passed as the `Limiter`'s
  `default_limits` and applies automatically to every route via `SlowAPIMiddleware`
  (registered in `app/main.py`), with no per-route decorator needed.
- `AUTH_RATE_LIMIT` (`Settings.auth_rate_limit`, default `"10/minute"`) overrides that default
  specifically on `/auth/login` and `/auth/callback` (`@limiter.limit(settings.auth_rate_limit)`
  in `app/auth.py`) — the more common target for abuse (credential stuffing, hammering the OAuth
  flow) gets a tighter ceiling than routine event CRUD.
- Both are `"<count>/<period>"` strings parsed by the `limits` library (`second`/`minute`/`hour`/
  `day`, singular or plural). Changing either in `.env` takes effect on the next container
  restart — `Settings` is loaded once at import time, not re-read live.

## Configuration

All settings are environment variables, loaded once at import time by `app/config.py`
(`Settings`); the process fails to start if any of the ones below without a default is missing.

| Variable | Notes |
|---|---|
| `GOOGLE_CLIENT_ID` | From Google Cloud Console. |
| `GOOGLE_CLIENT_SECRET` | From Google Cloud Console. |
| `GOOGLE_REDIRECT_URI` | Must match a registered redirect URI exactly. |
| `DATABASE_URL` | SQLAlchemy connection string. |
| `JWT_SECRET` | HS256 signing key. Auto-generated on first container boot (`docker-entrypoint.sh`), persisted in `data/.secrets.env`. Not user-supplied. |
| `TOKEN_ENCRYPTION_KEY` | Fernet key (32 bytes, base64-urlsafe). Same auto-generation as above. |
| `RATE_LIMIT` | Optional, default `"60/minute"`. See Rate limiting above. |
| `AUTH_RATE_LIMIT` | Optional, default `"10/minute"`. See Rate limiting above. |

## Development, testing, and CI

Local setup and everyday commands are documented in the top-level `README.md`. Test suite design
and how to run it: `README.md`'s "Running tests" section, `tests/conftest.py`,
`.github/workflows/tests.yml`. Recurrence rule (RRULE) syntax: `docs/rfc5545.md`.
