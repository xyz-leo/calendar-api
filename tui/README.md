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

1. **API server** — e.g. `http://localhost:8088` for local dev, or your deployed URL later.
2. **Standard timezone** — picked from a list (Brazilian and US timezones first, then a curated
   set of other common ones — not every timezone Google offers), defaulting to
   `America/Sao_Paulo`. Every event you create or edit through the TUI uses this one timezone;
   it's no longer a per-event field. Press **`o`** from the event list anytime afterward, then
   **Timezone**, to change it, or to just check the list of valid values — same picker either
   way. You can also set `"timezone"` directly in `config.json` to any [IANA/Olson
   identifier][iana-tz] (e.g. `"Europe/London"`), not just what's in the curated list.
3. **Log in with Google** — opens your system browser to the real Google consent screen. The
   TUI starts a temporary local server on its own (an OS-assigned free port, `127.0.0.1` only)
   to catch the token when it comes back, so there's nothing to copy — once you finish in the
   browser, the TUI picks up right where it left off. Press **`Escape`** to cancel (or just wait
   out the 5 minute timeout) if you change your mind or it's taking too long — either way, it
   just tries again.

[iana-tz]: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

Both server and token can be overridden per-run with env vars (`CALENDAR_API_SERVER`,
`CALENDAR_TOKEN`) without touching the saved config — useful for pointing at a different server
temporarily.

To reconfigure permanently, delete `~/.config/calendar-tui/config.json` and run again.

### Two list layouts

Press **`o`** from the event list, then **Layout**, to switch between two ways of presenting the
same events — the choice is remembered in `config.json["layout"]`.

**agenda** (the default) groups events by day, most recent first: a day header, then one line per
event — the time (or `all-day`) and the summary, a colored bullet marking each one. The
highlighted event gets a `>` in place of the bullet and its text recolored, instead of a full-row
highlight block. On `calendar-tui`, `ansi-dark`, and `ansi-light` (the three themes that share the
gold accent below), day headers are neon green instead, so a date doesn't read as just another
gold accent; every other theme uses its own accent color there.

Google's public Brazilian holiday calendar is merged in alongside your own events (see the root
`README.md`/`docs/api-reference.md` — the API does this, not the TUI). Holiday rows get a fixed
neon orange bullet instead of the theme's usual color, and `holiday` in place of a time, so they always
read as "not one of your own events" regardless of theme. They're read-only: `u`/`d` aren't
offered on a holiday event's detail screen, since there's nothing on your own calendar to update
or delete.

```
sat aug 1
  ● all-day   Deploy app!
  ● all-day   Rent Due
  ● holiday   Independence Day

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
above the list. Press **`o`**, then **Clock**, to show/hide it — the choice is remembered in
`~/.config/calendar-tui/config.json`.

### Filtering by date

Press **`f`** from the event list to open a small menu:

- **Today** / **This week** / **This month** — quick presets, always counted forward from right
  now (not calendar-aligned — "this week" means the next 7 days, not Sunday-to-Saturday).
- **Holidays only** — every one of this year's remaining holiday events (see above), no events of
  your own.
- **Pick month...** — type a month as `YYYY-MM` (e.g. `2026-08`) for the whole calendar month.
- **Pick date...** — type a single day as `YYYY-MM-DD` for just that day.
- **Clear filter** — only shown once a filter is active; goes back to the default "everything
  upcoming" view.

The active filter shows in the title ("Google Calendar Events — This month") and applies to
whichever layout you're in. It's not saved anywhere — every fresh launch starts back at the
default unfiltered view. Month/date picks are interpreted in your standard timezone (see above),
same as event creation.

### Options menu

Press **`o`** from the event list to open a menu grouping everything above that isn't an
everyday action: **Timezone**, **Themes**, **Toggle clock on/off**, **Toggle layout
(agenda/table)**, **Login**, **Logout**, and **Exit**. Picking one of the first four runs the
same thing its old dedicated key used to, then either opens the relevant picker or applies the
toggle immediately and closes the menu; **Exit** quits the app outright. Timezone and Themes are
both cancelable with **`Esc`** — backs out without changing anything, same either way — except
during the very first run, before a timezone is set at all, where there's nothing yet to cancel
back to and the key is disabled.

**Login** re-opens the same Google login screen used on first boot, for when the session JWT (or
the Google refresh token behind it — see below) has expired or gone invalid and you're seeing
`401` errors instead of your events. It doesn't log you out first — a successful login just
replaces the saved token. **Logout** is the opposite: asks for a typed `yes`, then tells the
server to forget its stored copy of your Google credentials and clears the local token, dropping
you back to the login screen on next launch.

The JWT itself is valid for **7 days** from whichever login minted it — matching how long Google
itself keeps a refresh token alive while this app's OAuth consent screen is still in Testing
status (see the root README). If you hit a `401` before then, either something logged you out
server-side or the underlying Google grant was revoked; **Login** above is the fix either way.

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

Press **`o`** from the event list, then **Themes**, to open the theme picker: an arrow-key list of
every available theme (Textual's built-ins — nord, dracula, gruvbox, catppuccin, etc. — plus the
custom one below), with a live preview as you move the highlight. `Enter` confirms and remembers
your choice
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

## Screenshots

...
