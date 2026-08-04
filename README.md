# Calendar API

A backend service that owns the relationship with Google Calendar so that nothing else has to.
Clients — web, TUI, mobile, third-party — talk only to this API. None of them ever hold a Google
credential or see a Google response shape directly.

```
Client (web / TUI / mobile / third-party)
    │
    ▼
API                  — auth, sessions, HTTP
    │
    ▼
CalendarService      — talks to Google, returns our own Event objects
    │
    ▼
Google Calendar API
```

**Status**: complete and in real use. Full event CRUD, recurring events, date-range filtering,
and real Google OAuth login — including a browser-based loopback flow so the terminal client
never needs a manual token — are all built, tested, and running against a real production
deployment behind a reverse proxy, on its own domain, with real TLS. This README documents what's
needed to set up and run it, whether that's your own local dev instance or a fresh deployment.

---

## Just want the TUI?

If an instance of this API is already running somewhere (your own deployment, or someone else's)
and you only want the terminal client, none of the rest of this README applies to you — skip
straight to [`tui/README.md`](tui/README.md). The short version:

```bash
git clone <this repo>
cd calendar-api
uv tool install --editable ./tui
calendar-tui
```

First run asks for the API's URL and your timezone, then opens Google login in your browser.
That's the entire setup — no Docker, no Google Cloud project, none of the steps below.

---

## Just want the web client?

Even less setup than the TUI: the API serves its own web client at `/` — visit the API's URL
(e.g. `https://calendar-api.learningsea.xyz`) in any modern browser, log in with Google, done. It's
a single self-contained page (`app/static/index.html`, no build step, no separate deployment) —
same-origin only by design (see `docs/architecture.md`'s Google OAuth section), read-only for now
(viewing/filtering events; create/update/delete are still TUI/`calctl.sh`-only).

---

## Prerequisites

### System dependencies

The only thing you need installed on your machine to run the API is **Docker + Docker Compose**.
Python, `uv`, and every other dependency live entirely inside the container — nothing else touches
your system. `uv` is only needed on the host if you also want to run the TUI client (see
`tui/README.md`).

See Docker's [install docs](https://docs.docker.com/engine/install/) for your OS. On Arch Linux:

```bash
sudo pacman -S --needed docker docker-compose
sudo systemctl enable --now docker.service
sudo usermod -aG docker $USER   # log out/in, or `newgrp docker`, for this to take effect
```

### A Google Cloud project (one per person running this)

This project doesn't ship or share a Google identity — every instance of it, whether that's your
own deployment or someone else's clone, needs its own Google Cloud project and its own OAuth
credentials. Nothing here is centrally shared.

1. Create a project at [console.cloud.google.com](https://console.cloud.google.com).
2. Enable the **Google Calendar API** (`APIs & Services → Library`, search for it, click
   **Enable**).
3. Configure the **OAuth consent screen** (`APIs & Services → OAuth consent screen`):
   - User type: **External**.
   - Scope: `.../auth/calendar.events` (read/write access to events — not the broader `calendar`
     scope, which also exposes calendar list/settings management this project doesn't need).
   - Add your own Google account (and anyone else testing) under **Test users**.

   While the app stays in **Testing** status, Google expires refresh tokens after **7 days** —
   you'll need to log in again weekly. That's fine for local development. Moving the app to
   **In production** later (a free process — add a privacy policy and homepage URL, then submit
   for Google's review) removes both that expiry and the 100-test-user cap.
4. Create credentials: `APIs & Services → Credentials → Create Credentials → OAuth client ID`,
   application type **Web application**. Add an **Authorized redirect URI** matching where you'll
   run the app, e.g. `http://localhost:8088/auth/callback`.
5. You'll get a **Client ID** and **Client Secret** — you'll need both in the next step.

### Environment variables

Copy the example file and fill in the values from your own Google Cloud setup:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `GOOGLE_CLIENT_ID` | OAuth Client ID from your Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | OAuth Client Secret from your Google Cloud Console |
| `GOOGLE_REDIRECT_URI` | Must exactly match a redirect URI registered in the Console, e.g. `http://localhost:8088/auth/callback` |
| `DATABASE_URL` | SQLite connection string; the default creates a local file |

`.env` is gitignored and never committed — each person running this project supplies their own
values.

Notice there's no JWT signing key or token-encryption key to fill in — those are internal secrets
with nothing external depending on their value, so the container generates both itself on first
boot and persists them in `data/.secrets.env`. Nothing to do here.

Two more variables are optional (sensible defaults if you omit them): `RATE_LIMIT` (default
`60/minute`, applies to every route) and `AUTH_RATE_LIMIT` (default `10/minute`, a stricter cap
specifically on `/auth/login`/`/auth/callback`) — both are per-client-IP request caps, `"<count>/
<period>"` strings. Change a value and restart the container to apply it; see
`docs/architecture.md`'s "Rate limiting" section for details.

---

## Running it

There are two `docker-compose` files — which one you want depends on what you're doing:

- **`docker-compose.dev.yml`** — local development. Use this one.
- **`docker-compose.yml`** (no `-f` flag needed) — production. Expects an external `shared_proxy`
  Docker network and a reverse proxy in front of it; not something a fresh local clone has set up,
  so don't reach for this unless you're actually deploying.

```bash
docker compose -f docker-compose.dev.yml up --build -d
```

That's the whole setup — it builds the image, installs dependencies, and starts the API in the
background. Check it's up:

```bash
curl http://localhost:8088/health
# {"status":"ok"}
```

Application code is bind-mounted into the container, so editing files under `app/` is reflected on
disk immediately — but the server itself doesn't auto-reload, so it needs restarting to actually
pick the change up:

```bash
docker compose -f docker-compose.dev.yml restart api
```

A full rebuild (`up --build -d` again) is only needed after changing dependencies in
`pyproject.toml`.

To stop it:

```bash
docker compose -f docker-compose.dev.yml down
```

The SQLite database file lives under `./data`, mounted into the container so it survives restarts
and rebuilds.

### Adding a dependency

No local Python or `uv` install is needed for this either — run it inside the running container,
which updates `pyproject.toml` and `uv.lock` on your host directly (they're bind-mounted):

```bash
docker compose -f docker-compose.dev.yml exec api uv add <package>
docker compose -f docker-compose.dev.yml up --build -d   # rebuild so the image picks it up
```

### Running tests

```bash
docker compose -f docker-compose.dev.yml exec api sh -c 'set -a; . /app/data/.secrets.env; set +a; uv run python -m pytest'
```

Sourcing `.secrets.env` first is only needed because `app.config.Settings` loads `JWT_SECRET`/
`TOKEN_ENCRYPTION_KEY` at import time — the main server process already has them from
`docker-entrypoint.sh`, but a one-off `exec` command doesn't inherit that unless you source the
file yourself, same as `calctl.sh` already does. `set -a` before sourcing (and `set +a` after) is
required, not optional — plain `. /app/data/.secrets.env` only sets the variables in the current
shell, it doesn't export them, so `uv run` (a separate child process) wouldn't actually see them.

Tests never touch Google or the real `data/calendar.db`: `CalendarService` tests use a fake
Google client object (queued canned responses instead of real API calls), and auth tests use a
fresh in-memory SQLite database per test.

---

## License

[MIT](LICENSE)
