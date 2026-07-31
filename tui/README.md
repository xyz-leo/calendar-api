# calendar-tui

Terminal client for `calendar-api`. Built with [Textual](https://textual.textualize.io/).

## Install

Requires `uv` (no system Python needed — `uv` manages its own).

```
uv tool install --editable ./tui
```

This puts a `calendar-tui` command on `PATH`. `--editable` means source edits under `tui/`
take effect immediately, no reinstall needed.

## Run

```
calendar-tui
```

First run asks for two things, once, and saves them to `~/.config/calendar-tui/config.json`:

1. **API server** — e.g. `http://localhost:8000` for local dev, or your deployed URL later.
2. **API token** — get one from a running API container with `./scripts/calctl.sh token`
   (reads it from `tmp/cli_token` after minting it). This is a stopgap until the TUI has its
   own OAuth login flow.

Both can be overridden per-run with env vars (`CALENDAR_API_SERVER`, `CALENDAR_TOKEN`) without
touching the saved config — useful for pointing at a different server temporarily.

To reconfigure permanently, delete `~/.config/calendar-tui/config.json` and run again.

## Dev loop

```
cd tui
uv run calendar-tui
```

Runs against the local venv `uv` manages for this subproject, same source as the installed
command.
