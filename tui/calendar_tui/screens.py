import re
from typing import Callable

from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Label, OptionList
from textual.widgets.option_list import Option

from . import api, config
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
    ]

    def __init__(self) -> None:
        super().__init__()
        self._events: dict[str, dict] = {}
        self._event_order: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="events-panel"):
            yield Clock(id="clock")
            yield Label("Google Calendar Events", id="events-title")
            yield DataTable(id="events")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Clock).display = config.show_clock(config.load())
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.action_refresh()

    def action_toggle_clock(self) -> None:
        cfg = config.load()
        shown = not config.show_clock(cfg)
        cfg["show_clock"] = shown
        config.save(cfg)
        self.query_one(Clock).display = shown

    def on_resize(self) -> None:
        self._render_table()

    def action_refresh(self) -> None:
        cfg = config.load()
        server = config.api_server(cfg)
        token = config.token(cfg)
        try:
            events = api.fetch_events(server, token)
        except api.ApiError as e:
            self.notify(str(e), severity="error")
            return
        self._events = {event["id"]: event for event in events}
        self._event_order = [event["id"] for event in events]
        self._render_table()

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
