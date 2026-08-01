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

First run asks for three things, once, and saves them to `~/.config/calendar-tui/config.json`:

1. **API server** — e.g. `http://localhost:8000` for local dev, or your deployed URL later.
2. **API token** — get one from a running API container with `./scripts/calctl.sh token`
   (reads it from `tmp/cli_token` after minting it). This is a stopgap until the TUI has its
   own OAuth login flow.
3. **Standard timezone** — picked from a list (Brazilian and US timezones first, then a curated
   set of other common ones — not every timezone Google offers), defaulting to
   `America/Sao_Paulo`. Every event you create or edit through the TUI uses this one timezone;
   it's no longer a per-event field. Press **`z`** from the event list anytime afterward to
   change it, or to just check the list of valid values — same picker either way. You can also
   set `"timezone"` directly in `config.json` to any [IANA/Olson identifier][iana-tz] (e.g.
   `"Europe/London"`), not just what's in the curated list.

[iana-tz]: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

Both server and token can be overridden per-run with env vars (`CALENDAR_API_SERVER`,
`CALENDAR_TOKEN`) without touching the saved config — useful for pointing at a different server
temporarily.

To reconfigure permanently, delete `~/.config/calendar-tui/config.json` and run again.

### Two list layouts

Press **`l`** to switch between two ways of presenting the same events — the choice is remembered
in `config.json["layout"]`.

**agenda** (the default) groups events by day, most recent first: a day header, then one line per
event — the time (or `all-day`) and the summary, a colored bullet marking each one. The
highlighted event gets a `>` in place of the bullet and its text recolored, instead of a full-row
highlight block. On `calendar-tui`, `ansi-dark`, and `ansi-light` (the three themes that share the
gold accent below), day headers are neon green instead, so a date doesn't read as just another
gold accent; every other theme uses its own accent color there.

```
sat aug 1
  ● all-day   ir koba!
  ● all-day   Rent Due

mon aug 3
  ● 03:00     Morning Run
```

**table** is the original dense view: Date, Summary, Location, and Description columns.
Summary and Location are fixed-width; Description stretches to fill whatever width is left and
reflows on terminal resize. Any text too long for its column is truncated with an ellipsis rather
than overflowing — on a narrow terminal (80 columns or less) the whole table still fits without a
horizontal scrollbar.

In both layouts, dates are shown as `YYYY-MM-DD — HH:MM` (agenda splits date and time across the
day header and the event line instead), with the UTC offset and seconds stripped — the event's
own timezone field already covers the former, and the latter is never meaningful here. All-day
events show no time at all — they're stored internally as midnight, but there's no real "00:00"
to show. The **table** layout also drops the year by default (`MM-DD — HH:MM`) since it's almost
always the current one — set `"show_year": true` in `config.json` to keep it. The detail screen
(below) always shows the full date regardless.

Press **`Enter`** on a selected event, in either layout, to see its full, untruncated details —
description, location, start/end, all-day, status, and ID; press **`Enter`** (or `Esc`) again to
go back. The detail box scales with the terminal (80% of its width, clamped to stay readable).

A small live clock (local system time, `tty-clock`-style block digits) plus today's date sits
above the list. Press **`c`** to show/hide it — the choice is remembered in
`~/.config/calendar-tui/config.json`.

### Creating, editing, and deleting events

- **`n`** from the event list opens a blank form (Summary, Description, Location, Start, End,
  Recurrence — timezone isn't a field here, every event uses the standard timezone set up above).
  `Tab`/`Shift+Tab` moves between fields.
- **`u`** from an event's detail screen opens the same form, pre-filled with that event's current
  values.
- **`ctrl+s`** in the form validates the required fields (Summary, Start) and shows a plain-text
  review of what's about to be sent — type **`yes`** and press `Enter` to actually save, anything
  else (or `Esc`) goes back to the form with your input untouched.
- **`d`** from an event's detail screen asks for the same `yes` confirmation, then deletes it.

All three return to the event list (refreshed) once the change actually goes through.

## Theming

`calendar-tui` ships with a near-black background, white body text, gold for titles/small
accents, and ruby red as the primary list/border/selection color — defined with fixed colors
rather than pulled from the terminal.

Press **`t`** from the event list to open the style picker: an arrow-key list of every available
theme (Textual's built-ins — nord, dracula, gruvbox, catppuccin, etc. — plus the custom one
below), with a live preview as you move the highlight. `Enter` confirms and remembers your choice
in `~/.config/calendar-tui/config.json`; `Esc` cancels and reverts. `ansi-dark`/`ansi-light` are
also replaced with this same ruby/gold palette, just with a transparent background that inherits
your terminal instead of a fixed one — useful if your terminal itself is transparent/blurred and
you want that to show through. Two vivid extras are also in the list: `neon-purple` (purple +
green) and `neon-yellow` (yellow + magenta).

First run also creates `~/.config/calendar-tui/theme.json` — the definition of the one custom
theme in that list (named `calendar-tui`), seeded with the defaults above. Edit any of the hex
values and restart to pick up the change — no other config needed:

```json
{
  "name": "calendar-tui",
  "dark": true,
  "ansi": false,
  "primary": "#cc6677",
  "secondary": "#a8505c",
  "accent": "#d4af37",
  "warning": "#d4af37",
  "error": "#e0616e",
  "success": "#d4af37",
  "foreground": "#ececec",
  "background": "#0d0d0d",
  "surface": "#131313",
  "panel": "#1c1717"
}
```

These map to [Textual's theme design tokens](https://textual.textualize.io/guide/design/) —
`primary`/`accent` drive most of the highlight colors, `background`/`surface`/`panel` are the
three layers of darkness used for the screen, panels, and table striping. Delete the file and
restart to regenerate it with the defaults.

## Dev loop

```
cd tui
uv run calendar-tui
```

Runs against the local venv `uv` manages for this subproject, same source as the installed
command.
