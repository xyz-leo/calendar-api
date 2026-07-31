import re
from typing import Callable

from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Label, OptionList
from textual.widgets.option_list import Option

from . import api, config
from .clock import Clock

_OFFSET_RE = re.compile(r"[+-]\d{2}:\d{2}$")


def _format_datetime(value: str) -> str:
    """'2026-08-15T08:00:00-03:00' -> '2026-08-15 — 08:00'.

    Drops the UTC offset (redundant — the event's own timezone field already
    covers it, and this app is single-user) and seconds (always :00 in
    practice, never useful here).
    """
    value = _OFFSET_RE.sub("", value)
    date_part, _, time_part = value.partition("T")
    if not time_part:
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
        ("t", "styles", "Styles"),
        ("c", "toggle_clock", "Clock"),
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
        table.add_column("Date", width=_DATE_WIDTH)
        table.add_column("Summary", width=_SUMMARY_WIDTH)
        table.add_column("Location", width=_LOCATION_WIDTH)
        table.add_column("Description", width=description_width)
        for event_id in self._event_order:
            event = self._events[event_id]
            table.add_row(
                _format_datetime(event["start"]),
                _truncate(event["summary"], _SUMMARY_WIDTH),
                _truncate(event.get("location") or "", _LOCATION_WIDTH),
                _truncate(event.get("description") or "", description_width),
                key=event_id,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        selected = self._events.get(event.row_key.value)
        if selected is not None:
            self.app.push_screen(EventDetailScreen(selected))

    def action_styles(self) -> None:
        self.app.push_screen(StylesScreen())


_DETAIL_FIELDS = [
    ("Summary", "summary"),
    ("Description", "description"),
    ("Location", "location"),
    ("Start", "start"),
    ("End", "end"),
    ("Timezone", "timezone"),
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
        return _format_datetime(value)
    return str(value)


class EventDetailScreen(Screen):
    """Full detail view for a single event. Enter or Escape goes back."""

    BINDINGS = [("enter", "back", "Back"), ("escape", "back", "Back")]

    def __init__(self, event: dict) -> None:
        super().__init__()
        self.event = event

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
