# Calendar API

I built this for myself, to manage my own calendar the way I wanted — not as a polished product
for a general audience. You're welcome to use or fork it, but a few decisions here (test-user
access being one) reflect that personal-project framing rather than a "designed for everyone" one.

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

## Before either of these: a real limitation, not a technicality

Both "just want the X?" sections below describe pointing a client at *a running instance* rather
than setting one up yourself. That only actually works if you're logged into a Google account
already added as a **test user** on that specific instance's Google Cloud project — every
deployment's OAuth consent screen defaults to **Testing** status (see [Prerequisites](#prerequisites)
below), and Google flatly refuses login for anyone not on that list, no exceptions, regardless of
whether the client software itself is running fine. This isn't a per-project setting you can
opt out of; it's how Google's OAuth consent screen works below "Published" status.

Concretely: my own deployment is in Testing status and I'm not adding outside test users to it —
pointing a client at it won't get you past Google's login screen. The two sections below apply if
either you set up your own free Google Cloud project and add yourself as its test user (a step in
Prerequisites, entirely under your own control), or someone running their own instance has
specifically added your account to theirs.

---

## Just want the TUI?

Assuming the above is sorted, and you only want the terminal client, none of the rest of this
README applies to you — skip straight to [`tui/README.md`](tui/README.md). The short version:

```bash
git clone <this repo>
cd calendar-api
uv tool install --editable ./tui
calendar-tui
```

First run asks for the API's URL and your timezone, then opens Google login in your browser.
That's the entire client-side setup — no Docker, no Google Cloud project *on your machine*, none
of the steps below (the Google Cloud project step still has to have happened somewhere, by
someone, for whichever instance you're pointing at).

### TUI Screenshots

#### Agenda View

<img width="300" height="350" alt="calendar-tui_agenda" src="https://github.com/user-attachments/assets/3977ba81-4e30-4a90-92fb-18257fab8d24" />

<img width="300" height="350" alt="calendar-tui_agenda-theme" src="https://github.com/user-attachments/assets/709134cd-f127-49c3-b30a-27c40391629b" />

#### Event and Task Creation

<img width="300" height="350" alt="calendar-tui_newevent" src="https://github.com/user-attachments/assets/a25de9a7-beb5-4551-b6f3-e47c87c507b6" />

#### Event and Task View

<img width="300" height="350" alt="calendar-tui_event" src="https://github.com/user-attachments/assets/03afa9c0-5235-4840-a1ac-e3025e0c34cd" />

---

## Just want the web client?

Same condition as above applies here too. Assuming it's met, this is even less setup than the
TUI: the API serves its own web client at `/` — visit that URL in any browser, log in with
Google, done. It's a single self-contained page (`app/static/index.html`, no build step, no
separate deployment) — same-origin only by design (see `docs/architecture.md`'s Google OAuth
section). Full event CRUD, same as the TUI: viewing, filtering, creating, editing, and deleting.

---

## A note on Google Tasks' due date

If you use the Task side of this app (as opposed to Events), there's one Google limitation worth
knowing about before you rely on it: **the "Deadline" field you see in Google's own apps doesn't
exist in the API this app is built on.**

When you create a task in Google's own apps (Google Calendar, the Tasks app, Gmail's task panel),
you actually get **two** separate date options: a plain **Date** field, and an optional
**Deadline** field underneath it. Only the plain **Date** field is exposed by the Google Tasks
API — Google simply doesn't hand the Deadline value over to anything reading a task through the
API, this app included. Setting a Deadline in Google's own UI has no effect here: this app can't
see it, can't read it, can't show it.

**Practical takeaway:** don't use Google's "Deadline" field at all when creating a task you want
this app to reflect correctly — it'll be invisible here. Put the date that actually matters (the
date you need the task done by) into the plain **Date** field instead, and treat that as the
deadline: it's the one date Google's API actually hands over, and it's what this app shows as a
task's "Due date." If you also want to track a separate start date for your own planning, the
workaround is to write it into the task's notes/description by hand, e.g. `start: 08/10`.

*(Short version, also shown in the app itself when viewing a task: Google's own "Deadline" field
isn't provided by its API — only the plain Date field is. Treat that Date field as the deadline;
it's the only date this app can see. For a separate start date, add it manually to the notes, e.g.
"start: 08/10".)*

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
