import calendar
import re
import threading
import webbrowser
from datetime import date, datetime, time
from typing import Callable
from zoneinfo import ZoneInfo

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical, VerticalScroll
from textual.geometry import Region
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Label, OptionList
from textual.widgets.option_list import Option

from . import api, config, oauth_login
from .clock import Clock
from .timezones import COMMON_TIMEZONES, DEFAULT_TIMEZONE

_OFFSET_RE = re.compile(r"[+-]\d{2}:\d{2}$")


def _format_datetime(value: str, all_day: bool = False, show_year: bool = True) -> str:
    """'2026-08-15T08:00:00-03:00' -> '2026-08-15 — 08:00'.

    Drops the UTC offset (redundant — the event's own timezone field already
    covers it, and this app is single-user) and seconds (always :00 in
    practice, never useful here). All-day events are stored internally as a
    midnight timestamp ("T00:00:00") even though they have no real time —
    the hour is dropped entirely for those rather than always showing a
    meaningless "00:00". show_year=False drops the leading "YYYY-" too
    (config.show_year, off by default) — only used in the event list, where
    every date is almost always the current year anyway.
    """
    value = _OFFSET_RE.sub("", value)
    date_part, _, time_part = value.partition("T")
    if not show_year:
        date_part = date_part[5:]
    if not time_part or all_day:
        return date_part
    hours_minutes = ":".join(time_part.split(":")[:2])
    return f"{date_part} — {hours_minutes}"


def _day_header(value: str, show_year: bool) -> str:
    """'2026-07-14T...' -> 'tue jul 14' ('tue jul 14 2026' if show_year)."""
    day = date.fromisoformat(_OFFSET_RE.sub("", value)[:10])
    fmt = "%a %b %-d %Y" if show_year else "%a %b %-d"
    return day.strftime(fmt).lower()


def _agenda_time_label(value: str, all_day: bool) -> str:
    if all_day:
        return "all-day"
    _, _, time_part = _OFFSET_RE.sub("", value).partition("T")
    return ":".join(time_part.split(":")[:2]) if time_part else "all-day"


# Theme-colored bullet on every row; swapped for a theme-colored ">" (same
# color as the title) on whichever row is currently highlighted, instead of a
# full-row background highlight.
_AGENDA_BULLET = "[$primary]●[/]"
_AGENDA_CURSOR = "[$accent]>[/]"


class SetupScreen(Screen):
    """Ask for a single missing config value, save it, then hand control back."""

    def __init__(self, field: str, prompt: str, placeholder: str, on_done: Callable[[], None]) -> None:
        super().__init__()
        self.field = field
        self.prompt = prompt
        self.placeholder = placeholder
        self.on_done = on_done

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="setup-box"):
                    yield Label("calendar-tui", id="setup-banner")
                    yield Label(self.prompt, id="setup-prompt")
                    yield Input(placeholder=self.placeholder, id="setup-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            return
        cfg = config.load()
        cfg[self.field] = value
        config.save(cfg)
        self.on_done()


_MANUAL_TOKEN_SETUP = ("token", "Paste your API token (get one with: calctl.sh token)", "eyJ...")


class LoginChoiceScreen(Screen):
    """First screen shown once an API server is configured but no token is —
    offers a real Google login (opens the browser) or the calctl.sh-based
    manual paste, unchanged from what SetupScreen always did on its own."""

    def __init__(self, api_server: str, on_done: Callable[[], None]) -> None:
        super().__init__()
        self.api_server = api_server
        self.on_done = on_done

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="login-choice-box"):
                    yield Label("Log in", id="login-choice-title")
                    yield OptionList(id="login-choice-list")
        yield Footer()

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.add_options(
            [
                Option("Log in with Google (opens your browser)", id="google"),
                Option("Paste a token manually", id="manual"),
            ]
        )
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id is None:
            return
        # Pop before pushing the next screen, same as every other transition in
        # this codebase — keeps exactly one screen on the stack at a time, which
        # is what lets on_done (ultimately app._advance) pop-then-push safely.
        self.app.pop_screen()
        if option_id == "google":
            self.app.push_screen(LoginWaitScreen(self.api_server, self.on_done))
        elif option_id == "manual":
            self.app.push_screen(SetupScreen(*_MANUAL_TOKEN_SETUP, self.on_done))


class LoginWaitScreen(Screen):
    """Starts a local loopback server, opens the system browser to
    /auth/login?port=<n>, and waits for the callback to carry the JWT back.
    Escape cancels; both success and failure return to LoginChoiceScreen (or,
    on success, hand off to on_done exactly like SetupScreen always did)."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    TIMEOUT_SECONDS = 300

    def __init__(self, api_server: str, on_done: Callable[[], None]) -> None:
        super().__init__()
        self.api_server = api_server
        self.on_done = on_done
        self._cancelled = threading.Event()

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="login-wait-box"):
                    yield Label("Waiting for you to finish in the browser...", id="login-wait-label")
                    yield Label("Press Escape to cancel.", id="login-wait-hint")
        yield Footer()

    def on_mount(self) -> None:
        self._wait_for_token()

    @work(thread=True)
    def _wait_for_token(self) -> None:
        server = oauth_login.LoopbackServer()
        webbrowser.open(f"{self.api_server.rstrip('/')}/auth/login?port={server.port}")
        token = server.serve_one(timeout=self.TIMEOUT_SECONDS, cancel_event=self._cancelled)
        # server.serve_one runs on this worker thread — call_from_thread is the
        # only safe way back into screen-stack/widget state from here.
        self.app.call_from_thread(self._handle_result, token)

    def _handle_result(self, token: str | None) -> None:
        if self._cancelled.is_set():
            # action_cancel already popped/pushed on the UI thread — this late
            # callback (the background thread noticing cancellation can lag a
            # beat behind it) has nothing left to do.
            return
        if token is None:
            self.notify("Login timed out or failed.", severity="error")
            self.app.pop_screen()
            self.app.push_screen(LoginChoiceScreen(self.api_server, self.on_done))
            return
        cfg = config.load()
        cfg["token"] = token
        config.save(cfg)
        # No self.app.pop_screen() here — on_done (app._advance) already does
        # exactly one pop before pushing the next screen, same contract
        # SetupScreen/TimezoneScreen rely on. Popping here too was a real bug:
        # it emptied the stack down to just Textual's implicit base screen,
        # and _advance's own pop then had nothing left to pop.
        self.on_done()

    def action_cancel(self) -> None:
        self._cancelled.set()
        self.app.pop_screen()
        self.app.push_screen(LoginChoiceScreen(self.api_server, self.on_done))


class TimezoneScreen(Screen):
    """Pick the one standard timezone used for every event — forced on first
    boot (via on_done, same pop-then-push pattern as SetupScreen), and
    reachable anytime after via `z` from the event list to change it or just
    check the list of valid values."""

    def __init__(self, on_done: Callable[[], None]) -> None:
        super().__init__()
        self.on_done = on_done

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="timezone-box"):
                    yield Label("Pick your standard timezone", id="timezone-title")
                    yield OptionList(id="timezone-list")
        yield Footer()

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.add_options(Option(tz, id=tz) for tz in COMMON_TIMEZONES)
        current = config.timezone(config.load()) or DEFAULT_TIMEZONE
        if current in COMMON_TIMEZONES:
            option_list.highlighted = COMMON_TIMEZONES.index(current)
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not event.option.id:
            return
        cfg = config.load()
        cfg["timezone"] = event.option.id
        config.save(cfg)
        self.on_done()


_DATE_WIDTH = 18  # "YYYY-MM-DD — HH:MM"
_SUMMARY_WIDTH = 22
_LOCATION_WIDTH = 12
_MIN_DESCRIPTION_WIDTH = 12
# 2 cells of padding per column (Textual's DataTable default cell_padding=1 on
# each side) across our 4 columns, plus a little slack for the scrollbar.
_COLUMN_OVERHEAD = 4 * 2 + 2


def _truncate(text: str, max_length: int) -> str:
    """Cut text to fit its column, marking the cut with an ellipsis.

    DataTable doesn't truncate cell content on its own — anything wider than
    its column just overflows the table's visible area, which is what was
    forcing horizontal scrolling (and the panel border getting cut off) on
    narrow terminals.
    """
    if len(text) <= max_length:
        return text
    if max_length <= 1:
        return text[:max_length]
    return text[: max_length - 1] + "…"


class EventListScreen(Screen):
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("n", "create", "New"),
        ("t", "styles", "Styles"),
        ("c", "toggle_clock", "Clock"),
        ("z", "change_timezone", "Timezone"),
        ("l", "toggle_layout", "Layout"),
        ("f", "filter", "Filter"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._events: dict[str, dict] = {}
        self._event_order: list[str] = []
        self._agenda_highlighted: str | None = None
        self._agenda_group_header: dict[str, int] = {}
        # None = no filter, showing everything upcoming (the default). Reset
        # every launch — deliberately not persisted like theme/layout/timezone.
        self._filter_params: dict | None = None
        self._filter_label: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="events-panel"):
            yield Clock(id="clock")
            yield Label("Google Calendar Events", id="events-title")
            yield DataTable(id="events")
            yield OptionList(id="events-agenda")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Clock).display = config.show_clock(config.load())
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.action_refresh()
        self._apply_layout(config.layout(config.load()))

    def action_toggle_clock(self) -> None:
        cfg = config.load()
        shown = not config.show_clock(cfg)
        cfg["show_clock"] = shown
        config.save(cfg)
        self.query_one(Clock).display = shown

    def action_toggle_layout(self) -> None:
        cfg = config.load()
        new_layout = "agenda" if config.layout(cfg) == "table" else "table"
        cfg["layout"] = new_layout
        config.save(cfg)
        self._apply_layout(new_layout)

    def _apply_layout(self, layout: str) -> None:
        table = self.query_one(DataTable)
        agenda = self.query_one("#events-agenda", OptionList)
        table.display = layout == "table"
        agenda.display = layout == "agenda"
        if layout == "agenda":
            agenda.focus()
        else:
            table.focus()

    def on_resize(self) -> None:
        self._render_table()

    def action_refresh(self) -> None:
        cfg = config.load()
        server = config.api_server(cfg)
        token = config.token(cfg)
        try:
            events = api.fetch_events(server, token, params=self._filter_params)
        except api.ApiError as e:
            self.notify(str(e), severity="error")
            return
        self._events = {event["id"]: event for event in events}
        self._event_order = [event["id"] for event in events]
        self._render_table()
        self._render_agenda()

    def action_filter(self) -> None:
        self.app.push_screen(FilterScreen(self._filter_label, self._apply_filter))

    def _apply_filter(self, params: dict | None, label: str | None) -> None:
        self._filter_params = params
        self._filter_label = label
        title = "Google Calendar Events" if label is None else f"Google Calendar Events — {label}"
        self.query_one("#events-title", Label).update(title)
        self.action_refresh()

    def _description_width(self) -> int:
        table = self.query_one(DataTable)
        fixed = _DATE_WIDTH + _SUMMARY_WIDTH + _LOCATION_WIDTH + _COLUMN_OVERHEAD
        return max(_MIN_DESCRIPTION_WIDTH, table.size.width - fixed)

    def _render_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        description_width = self._description_width()
        show_year = config.show_year(config.load())
        table.add_column("Date", width=_DATE_WIDTH)
        table.add_column("Summary", width=_SUMMARY_WIDTH)
        table.add_column("Location", width=_LOCATION_WIDTH)
        table.add_column("Description", width=description_width)
        for event_id in self._event_order:
            event = self._events[event_id]
            table.add_row(
                _format_datetime(event["start"], event.get("all_day", False), show_year),
                _truncate(event["summary"], _SUMMARY_WIDTH),
                _truncate(event.get("location") or "", _LOCATION_WIDTH),
                _truncate(event.get("description") or "", description_width),
                key=event_id,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        selected = self._events.get(event.row_key.value)
        if selected is not None:
            self.app.push_screen(EventDetailScreen(selected, on_change=self.action_refresh))

    def _agenda_label(self, event: dict, marker: str) -> str:
        time_label = _agenda_time_label(event["start"], event.get("all_day", False))
        return f"  {marker} {time_label:<9} {event['summary']}"

    def _render_agenda(self) -> None:
        # Alternate presentation of the exact same data as the table — grouped
        # by calendar day, day headers and the blank line before each group as
        # disabled (unselectable) options, so up/down and Enter only ever land
        # on real events. Relies on events already arriving in chronological
        # order from the API: an all-day event's own internal timestamp is
        # midnight, always earlier than any timed event the same day, so it
        # naturally sorts first within its day with no extra sorting needed.
        option_list = self.query_one("#events-agenda", OptionList)
        option_list.clear_options()
        self._agenda_highlighted = None
        self._agenda_group_header = {}
        show_year = config.show_year(config.load())
        current_day = None
        for event_id in self._event_order:
            event = self._events[event_id]
            day = event["start"][:10]
            if day != current_day:
                if current_day is not None:
                    option_list.add_option(Option(" ", disabled=True))
                option_list.add_option(Option(_day_header(event["start"], show_year), disabled=True))
                self._agenda_group_header[event_id] = option_list.option_count - 1
                current_day = day
            option_list.add_option(Option(self._agenda_label(event, _AGENDA_BULLET), id=event_id))
        # OptionList doesn't auto-highlight anything until the first keypress —
        # start on the first real event (skipping the leading day header) so
        # there's always a visible cursor position, same as StylesScreen/
        # TimezoneScreen already do. Setting .highlighted fires the same
        # OptionHighlighted event a keypress would, so the "> " marker below
        # still gets applied to it.
        for index in range(option_list.option_count):
            if not option_list.get_option_at_index(index).disabled:
                option_list.highlighted = index
                break

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        # Swap the bullet for "> " on whichever row is current, instead of
        # using OptionList's default full-row background highlight (see
        # #events-agenda > .option-list--option-highlighted in app.tcss,
        # which turns that background off).
        option_list = event.option_list
        if self._agenda_highlighted and self._agenda_highlighted in self._events:
            previous = self._events[self._agenda_highlighted]
            option_list.replace_option_prompt(
                self._agenda_highlighted, self._agenda_label(previous, _AGENDA_BULLET)
            )
        new_id = event.option.id
        if new_id and new_id in self._events:
            option_list.replace_option_prompt(new_id, self._agenda_label(self._events[new_id], _AGENDA_CURSOR))
        self._agenda_highlighted = new_id
        # OptionList.scroll_to_highlight (already run by the time this handler
        # fires) only scrolls the minimum needed to reveal the highlighted
        # line itself — for the first event in a day group, that can leave
        # the day header sitting just above the viewport, scrolled out of
        # view until you nudge the scrollbar with the mouse. Re-run the
        # scroll with a region that also covers that header so it's always
        # pulled back into view together with the event under it.
        header_index = self._agenda_group_header.get(new_id)
        if header_index is not None:
            try:
                top = option_list._index_to_line[header_index]
                bottom = (
                    option_list._index_to_line[event.option_index] + option_list._heights[event.option_index]
                )
            except KeyError:
                pass  # Line cache not built yet (e.g. before first layout) — nothing to scroll.
            else:
                option_list.scroll_to_region(
                    Region(0, top, option_list.scrollable_content_region.width, bottom - top),
                    animate=False,
                    force=True,
                    immediate=True,
                )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not event.option.id:
            return
        selected = self._events.get(event.option.id)
        if selected is not None:
            self.app.push_screen(EventDetailScreen(selected, on_change=self.action_refresh))

    def action_create(self) -> None:
        self.app.push_screen(EventFormScreen(None, on_saved=self.action_refresh))

    def action_styles(self) -> None:
        self.app.push_screen(StylesScreen())

    def action_change_timezone(self) -> None:
        self.app.push_screen(TimezoneScreen(self.app.pop_screen))


_DETAIL_FIELDS = [
    ("Summary", "summary"),
    ("Description", "description"),
    ("Location", "location"),
    ("Start", "start"),
    ("End", "end"),
    ("All day", "all_day"),
    ("Status", "status"),
    ("ID", "id"),
]


_DATETIME_FIELDS = {"start", "end"}


def _detail_value(event: dict, field: str) -> str:
    value = event.get(field)
    if value is None or value == "":
        return "—"
    if field in _DATETIME_FIELDS:
        return _format_datetime(value, event.get("all_day", False))
    return str(value)


class EventDetailScreen(Screen):
    """Full detail view for a single event. Enter or Escape goes back."""

    BINDINGS = [
        ("enter", "back", "Back"),
        ("escape", "back", "Back"),
        ("u", "update", "Update"),
        ("d", "delete", "Delete"),
    ]

    def __init__(self, event: dict, on_change: Callable[[], None]) -> None:
        super().__init__()
        self.event = event
        self.on_change = on_change

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail-box"):
            yield Label(self.event.get("summary") or "(no summary)", id="detail-title")
            for label, field in _DETAIL_FIELDS[1:]:
                yield Label(
                    f"{label}: {_detail_value(self.event, field)}",
                    classes="detail-field",
                )
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_update(self) -> None:
        self.app.push_screen(EventFormScreen(self.event, on_saved=self._handle_saved))

    def _handle_saved(self) -> None:
        self.on_change()
        self.app.pop_screen()

    def action_delete(self) -> None:
        summary = self.event.get("summary") or "(no summary)"
        self.app.push_screen(
            ConfirmScreen(
                f"Delete '{summary}'?\n\nType yes to confirm.",
                on_confirm=self._perform_delete,
            )
        )

    def _perform_delete(self) -> None:
        cfg = config.load()
        try:
            api.delete_event(config.api_server(cfg), config.token(cfg), self.event["id"])
        except api.ApiError as e:
            self.notify(str(e), severity="error")
            return
        self.on_change()
        self.app.pop_screen()


class ConfirmScreen(Screen):
    """Generic "type yes to confirm" prompt. Enter+"yes" confirms (pops itself
    first, then calls on_confirm); anything else, or Escape, cancels."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, message: str, on_confirm: Callable[[], None]) -> None:
        super().__init__()
        self.message = message
        self.on_confirm = on_confirm

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="confirm-box"):
                    yield Label(self.message, id="confirm-message")
                    yield Input(placeholder="yes", id="confirm-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        confirmed = event.value.strip().lower() == "yes"
        self.app.pop_screen()
        if confirmed:
            self.on_confirm()

    def action_cancel(self) -> None:
        self.app.pop_screen()


_RECURRENCE_PREFIXES = ("RRULE:", "EXRULE:", "RDATE:", "EXDATE:")

_FORM_FIELDS = [
    ("Summary", "summary", ""),
    ("Description", "description", ""),
    ("Location", "location", ""),
    ("Start (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)", "start", ""),
    ("End (blank = all-day, +1 day)", "end", ""),
    ("Recurrence (RRULE, optional, e.g. FREQ=WEEKLY;COUNT=4)", "recurrence", ""),
]


class EventFormScreen(Screen):
    """Create (event=None) or edit (event=<existing>) an event. `ctrl+s`
    reviews the entered values via ConfirmScreen before actually saving."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "review", "Review")]

    def __init__(self, event: dict | None, on_saved: Callable[[], None]) -> None:
        super().__init__()
        self.event = event
        self.on_saved = on_saved

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="form-box"):
            yield Label("New Event" if self.event is None else "Edit Event", id="form-title")
            for label, field, default in _FORM_FIELDS:
                yield Label(label, classes="form-label")
                yield Input(value=self._prefill(field, default), id=f"form-{field}")
        yield Footer()

    def _prefill(self, field: str, default: str) -> str:
        if self.event is None:
            return default
        if field == "recurrence":
            recurrence = self.event.get("recurrence")
            if not recurrence:
                return default
            first = recurrence[0]
            return first.split(":", 1)[1] if ":" in first else first
        if field in ("start", "end"):
            value = self.event.get(field)
            if not value:
                return default
            # All-day events store a full "date + T00:00:00" timestamp — trim
            # back to just the date, otherwise resubmitting unchanged would
            # silently turn it into a timed event (a full timestamp always
            # means "timed" to EventInput, a bare date always means "all-day").
            return value[:10] if self.event.get("all_day") else value
        return self.event.get(field) or default

    def on_mount(self) -> None:
        self.query_one("#form-summary", Input).focus()

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def _value(self, field: str) -> str:
        return self.query_one(f"#form-{field}", Input).value.strip()

    def _collect_payload(self) -> dict:
        payload = {
            "summary": self._value("summary"),
            "description": self._value("description"),
            "location": self._value("location"),
            "start": self._value("start"),
            "timezone": config.timezone(config.load()) or DEFAULT_TIMEZONE,
        }
        end = self._value("end")
        if end:
            payload["end"] = end
        recurrence = self._value("recurrence")
        if recurrence:
            if not recurrence.upper().startswith(_RECURRENCE_PREFIXES):
                recurrence = f"RRULE:{recurrence}"
            payload["recurrence"] = [recurrence]
        return payload

    def action_review(self) -> None:
        payload = self._collect_payload()
        if not payload["summary"]:
            self.notify("Summary is required.", severity="error")
            return
        if not payload["start"]:
            self.notify("Start is required.", severity="error")
            return
        self.app.push_screen(ConfirmScreen(self._format_resume(payload), on_confirm=lambda: self._save(payload)))

    def _format_resume(self, payload: dict) -> str:
        verb = "Create" if self.event is None else "Update"
        lines = [f"{verb} event:", "", f"Summary: {payload['summary']}"]
        if payload.get("description"):
            lines.append(f"Description: {payload['description']}")
        if payload.get("location"):
            lines.append(f"Location: {payload['location']}")
        lines.append(f"Start: {payload['start']}")
        if payload.get("end"):
            lines.append(f"End: {payload['end']}")
        if payload.get("recurrence"):
            lines.append(f"Recurrence: {payload['recurrence'][0]}")
        lines.append("")
        lines.append("Type yes to confirm.")
        return "\n".join(lines)

    def _save(self, payload: dict) -> None:
        cfg = config.load()
        server = config.api_server(cfg)
        token = config.token(cfg)
        try:
            if self.event is None:
                api.create_event(server, token, payload)
            else:
                api.update_event(server, token, self.event["id"], payload)
        except api.ApiError as e:
            self.notify(str(e), severity="error")
            return
        self.app.pop_screen()
        self.on_saved()


class StylesScreen(Screen):
    """Live-preview picker over every registered theme (built-in + our own)."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="styles-box"):
                    yield Label("Pick a style", id="styles-title")
                    yield OptionList(id="styles-list")
        yield Footer()

    def on_mount(self) -> None:
        self._original_theme = self.app.theme
        names = sorted(self.app.available_themes)
        option_list = self.query_one(OptionList)
        option_list.add_options(Option(name, id=name) for name in names)
        if self._original_theme in names:
            option_list.highlighted = names.index(self._original_theme)
        option_list.focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id:
            self.app.theme = event.option.id

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not event.option.id:
            return
        cfg = config.load()
        cfg["theme"] = event.option.id
        config.save(cfg)
        self.app.pop_screen()

    def action_cancel(self) -> None:
        self.app.theme = self._original_theme
        self.app.pop_screen()


class _FilterPromptScreen(Screen):
    """Single free-text input for a custom filter value (a month or a date).

    Always pops itself back to whatever pushed it (the FilterScreen menu) on
    Enter — validation happens in on_submit, called after that pop, so an
    invalid value just lands the user back on the menu with an error notice
    instead of a dead-end retry loop in the input itself.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, placeholder: str, on_submit: Callable[[str], None]) -> None:
        super().__init__()
        self.prompt = prompt
        self.placeholder = placeholder
        self.on_submit = on_submit

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="filter-prompt-box"):
                    yield Label(self.prompt, id="filter-prompt-label")
                    yield Input(placeholder=self.placeholder, id="filter-prompt-input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            return
        self.app.pop_screen()
        self.on_submit(value)

    def action_cancel(self) -> None:
        self.app.pop_screen()


class FilterScreen(Screen):
    """Pick a date-range filter for the event list, or clear the current one.

    Presets ("Today"/"This week"/"This month") map straight onto the API's
    own `range` query param (always "from now", not calendar-aligned — same
    as the API). "Pick month..."/"Pick date..." open a small text prompt and
    compute explicit `from`/`to` bounds instead.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    _PRESETS = [("Today", "today"), ("This week", "week"), ("This month", "month")]

    def __init__(self, active_label: str | None, on_apply: Callable[[dict | None, str | None], None]) -> None:
        super().__init__()
        self.active_label = active_label
        self.on_apply = on_apply

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="filter-box"):
                    yield Label("Filter by date", id="filter-title")
                    yield OptionList(id="filter-list")
        yield Footer()

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        options = [Option(label, id=f"range:{key}") for label, key in self._PRESETS]
        options.append(Option("Pick month...", id="pick-month"))
        options.append(Option("Pick date...", id="pick-date"))
        if self.active_label is not None:
            options.append(Option("Clear filter", id="clear"))
        option_list.add_options(options)
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id is None:
            return
        if option_id == "clear":
            self.app.pop_screen()
            self.on_apply(None, None)
        elif option_id.startswith("range:"):
            key = option_id.split(":", 1)[1]
            label = next(label for label, k in self._PRESETS if k == key)
            self.app.pop_screen()
            self.on_apply({"range": key}, label)
        elif option_id == "pick-month":
            self.app.push_screen(_FilterPromptScreen("Month (YYYY-MM)", "2026-08", self._submit_month))
        elif option_id == "pick-date":
            self.app.push_screen(_FilterPromptScreen("Date (YYYY-MM-DD)", "2026-08-15", self._submit_date))

    def _standard_timezone(self) -> ZoneInfo:
        return ZoneInfo(config.timezone(config.load()) or DEFAULT_TIMEZONE)

    def _submit_month(self, value: str) -> None:
        try:
            year_str, month_str = value.split("-", 1)
            year, month = int(year_str), int(month_str)
            if not 1 <= month <= 12:
                raise ValueError
        except ValueError:
            self.notify("Expected YYYY-MM, e.g. 2026-08.", severity="error")
            return
        tz = self._standard_timezone()
        last_day = calendar.monthrange(year, month)[1]
        from_ = datetime(year, month, 1, tzinfo=tz)
        to = datetime(year, month, last_day, 23, 59, 59, tzinfo=tz)
        label = date(year, month, 1).strftime("%B %Y")
        self.app.pop_screen()
        self.on_apply({"from": from_.isoformat(), "to": to.isoformat()}, label)

    def _submit_date(self, value: str) -> None:
        try:
            day = date.fromisoformat(value)
        except ValueError:
            self.notify("Expected YYYY-MM-DD, e.g. 2026-08-15.", severity="error")
            return
        tz = self._standard_timezone()
        from_ = datetime.combine(day, time.min, tzinfo=tz)
        to = datetime.combine(day, time.max.replace(microsecond=0), tzinfo=tz)
        label = day.strftime("%b %-d, %Y").lower()
        self.app.pop_screen()
        self.on_apply({"from": from_.isoformat(), "to": to.isoformat()}, label)

    def action_cancel(self) -> None:
        self.app.pop_screen()
