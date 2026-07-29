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

**Status**: early development. Architecture is defined; the application scaffold is in progress.
This README currently documents what's needed to set up and run the project.

---

## Prerequisites

### System dependencies

The only thing you need installed on your machine is **Docker + Docker Compose**. Python, `uv`,
and every other dependency live entirely inside the container — nothing else touches your system.

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
   run the app, e.g. `http://localhost:8000/auth/callback`.
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
| `GOOGLE_REDIRECT_URI` | Must exactly match a redirect URI registered in the Console, e.g. `http://localhost:8000/auth/callback` |
| `DATABASE_URL` | SQLite connection string; the default creates a local file |

`.env` is gitignored and never committed — each person running this project supplies their own
values.

Notice there's no JWT signing key or token-encryption key to fill in — those are internal secrets
with nothing external depending on their value, so the container generates both itself on first
boot and persists them in `data/.secrets.env`. Nothing to do here.

---

## Running it

```bash
docker compose up --build -d
```

That's the whole setup — it builds the image, installs dependencies, and starts the API in the
background. Check it's up:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Application code is bind-mounted into the container and the server runs with auto-reload, so
editing files under `app/` takes effect immediately — no rebuild needed. A rebuild
(`docker compose up --build -d` again) is only required after changing dependencies in
`pyproject.toml`.

To stop it:

```bash
docker compose down
```

The SQLite database file lives under `./data`, mounted into the container so it survives restarts
and rebuilds.

### Adding a dependency

No local Python or `uv` install is needed for this either — run it inside the running container,
which updates `pyproject.toml` and `uv.lock` on your host directly (they're bind-mounted):

```bash
docker compose exec api uv add <package>
docker compose up --build -d   # rebuild so the image picks it up
```

---

## License

[MIT](LICENSE)
