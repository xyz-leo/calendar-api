import calendar
import re
import threading
import webbrowser
from datetime import date, datetime, time
from typing import Callable
from zoneinfo import ZoneInfo

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Middle, Vertical, VerticalScroll
from textual.geometry import Region
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Label, OptionList, Static
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
# Holiday events (merged in from Google's public holiday calendar, see
# app/calendar_service.py's HOLIDAY_CALENDAR_ID) get a fixed color instead of
# the theme's primary/accent, so they read as "not one of your own events"
# consistently across every theme rather than blending in with the rest of
# the agenda.
_HOLIDAY_BULLET = "[#ff6a00]●[/]"
_HOLIDAY_CURSOR = "[#ff6a00]>[/]"

_REPO_URL = "https://github.com/xyz-leo/calendar-api"


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


class LoginWaitScreen(Screen):
    """Starts a local loopback server, opens the system browser to
    /auth/login?port=<n>, and waits for the callback to carry the JWT back.
    This is the only login path the TUI offers — Google auth already covers
    everything a manual-token dev shortcut used to (that path was removed
    outright, not just hidden, once this one was working end to end).

    A timeout retries automatically (opens the browser again). Escape is a
    real cancel, not a retry — it calls on_cancel, which defaults to just
    popping this screen (fine whenever something's already underneath, e.g.
    the re-login/post-logout call sites below). First boot has nothing
    underneath yet, so app.py's call site passes its own on_cancel that
    lands on an empty EventListScreen instead — see there for why.

    Success hands off to on_done, exactly like SetupScreen always did."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("r", "open_readme", "Open README")]
    TIMEOUT_SECONDS = 300

    def __init__(
        self,
        api_server: str,
        on_done: Callable[[], None],
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.api_server = api_server
        self.on_done = on_done
        self.on_cancel = on_cancel
        self._cancelled = threading.Event()

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="login-wait-box"):
                    yield Label("Waiting for you to finish in the browser...", id="login-wait-label")
                    yield Label("Press Escape to cancel.", id="login-wait-hint")
                    yield Label(
                        "If the owner of this server invited you, just log in — nothing else "
                        "needed. Otherwise, to use this yourself: create a free Google Cloud "
                        "project and add your own GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET to .env, "
                        "then self-host. (Google blocks login for anyone not added as a test "
                        "user on someone else's project.)",
                        id="login-wait-notice",
                    )
                    # Text object with an explicit link style, not markup — see AboutScreen's
                    # own link for why ("[link=...]" raises MarkupError on Textual's parser).
                    yield Label(
                        Text(
                            "Press r to check the README on GitHub for more info",
                            style=f"link {_REPO_URL} underline",
                        ),
                        id="login-wait-readme-link",
                    )
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
            self.notify("Login timed out or failed. Trying again.", severity="error")
            self.app.pop_screen()
            self.app.push_screen(LoginWaitScreen(self.api_server, self.on_done, self.on_cancel))
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
        if self.on_cancel is not None:
            self.on_cancel()
        else:
            self.app.pop_screen()

    def action_open_readme(self) -> None:
        webbrowser.open(_REPO_URL)


class TimezoneScreen(Screen):
    """Pick the one standard timezone used for every event — forced on first
    boot (via on_done, same pop-then-push pattern as SetupScreen), and
    reachable anytime after via the options menu to change it or just check
    the list of valid values.

    cancellable=False during the forced first-boot step: there's nothing
    behind this screen yet to cancel back to, so Escape is disabled there
    (check_action hides it from the footer entirely, rather than leaving a
    dead key visible). Every other use (options menu) leaves it True.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, on_done: Callable[[], None], *, cancellable: bool = True) -> None:
        super().__init__()
        self.on_done = on_done
        self.cancellable = cancellable

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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "cancel" and not self.cancellable:
            return None  # Hide the binding from the footer instead of leaving a dead key.
        return True

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not event.option.id:
            return
        cfg = config.load()
        cfg["timezone"] = event.option.id
        config.save(cfg)
        self.on_done()

    def action_cancel(self) -> None:
        self.app.pop_screen()


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
        ("c", "calendar", "Calendar"),
        ("n", "create", "New event"),
        ("o", "options", "Options"),
        ("a", "about", "About"),
        ("f", "filter", "Filter"),
        ("escape", "clear_filter", "Clear filter"),
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
            # Center wraps only the agenda list (table view stays full-width,
            # unaffected) — Textual's align only re-centers a container's
            # *whole* child group by their combined bounding box, so putting
            # #events-agenda alone in its own Center is what actually makes
            # it individually centered instead of the panel's full-width
            # siblings (Clock/title) pinning that bounding box to full width.
            with Center(id="agenda-center"):
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
        agenda_center = self.query_one("#agenda-center", Center)
        agenda = self.query_one("#events-agenda", OptionList)
        table.display = layout == "table"
        # Toggling just the OptionList's own display left its wrapping Center
        # (#agenda-center) still occupying its height: 1fr slot in the panel's
        # Vertical even while hidden — #events and #agenda-center both being
        # 1fr split the available height 50/50 in table view instead of the
        # table getting all of it. The wrapper itself has to be hidden too.
        agenda_center.display = layout == "agenda"
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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # "Clear filter" only makes sense once a filter is actually active —
        # hide it from the footer entirely rather than leaving a dead key,
        # same pattern TimezoneScreen/EventDetailScreen already use elsewhere.
        if action == "clear_filter" and self._filter_label is None:
            return None
        return True

    def action_filter(self) -> None:
        self.app.push_screen(FilterScreen(self._filter_label, self._apply_filter))

    def action_clear_filter(self) -> None:
        self._apply_filter(None, None)

    def action_calendar(self) -> None:
        # Reuses the exact same callback FilterScreen's presets/pickers call —
        # picking a day in the calendar is just another way to produce the same
        # (params, label) pair "Pick date..." already does.
        self.app.push_screen(CalendarScreen(self._apply_filter))

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

    def _agenda_label(self, event: dict, *, highlighted: bool) -> str:
        is_holiday = event.get("is_holiday", False)
        if is_holiday:
            marker = _HOLIDAY_CURSOR if highlighted else _HOLIDAY_BULLET
            time_label = "holiday"
        else:
            marker = _AGENDA_CURSOR if highlighted else _AGENDA_BULLET
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
            option_list.add_option(Option(self._agenda_label(event, highlighted=False), id=event_id))
        # OptionList doesn't auto-highlight anything until the first keypress —
        # start on the first real event (skipping the leading day header) so
        # there's always a visible cursor position, same as ThemesScreen/
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
                self._agenda_highlighted, self._agenda_label(previous, highlighted=False)
            )
        new_id = event.option.id
        if new_id and new_id in self._events:
            option_list.replace_option_prompt(
                new_id, self._agenda_label(self._events[new_id], highlighted=True)
            )
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

    def action_options(self) -> None:
        self.app.push_screen(
            OptionsScreen(
                on_timezone=self.action_change_timezone,
                on_themes=self.action_themes,
                on_toggle_clock=self.action_toggle_clock,
                on_toggle_layout=self.action_toggle_layout,
                on_login=self.action_login,
                on_logout=self.action_logout,
            )
        )

    def action_themes(self) -> None:
        self.app.push_screen(ThemesScreen())

    def action_about(self) -> None:
        self.app.push_screen(AboutScreen())

    def action_change_timezone(self) -> None:
        self.app.push_screen(TimezoneScreen(self.app.pop_screen))

    def action_login(self) -> None:
        # Re-runs the same Google login flow used on first boot — for when the
        # JWT (or the Google refresh token behind it) has expired or gone
        # invalid without an explicit logout, so there's a way back in besides
        # deleting config.json by hand. Doesn't touch the current token first;
        # a successful login just overwrites it, same as _perform_logout's own
        # push below (on_done=self.app.pop_screen keeps this screen on the
        # stack underneath, so success lands right back here, not a rebuild).
        cfg = config.load()
        self.app.push_screen(LoginWaitScreen(config.api_server(cfg), self.app.pop_screen))

    def action_logout(self) -> None:
        self.app.push_screen(
            ConfirmScreen(
                "Log out?\n\n"
                "The server forgets its stored copy of your Google credentials — "
                "calendar-api won't be able to access your calendar again until you "
                "log in with Google here. This does not revoke access on Google's own "
                "end (Google Account -> Security -> Third-party access, if you want "
                "to remove it there too).\n\n"
                "Type yes to confirm.",
                on_confirm=self._perform_logout,
            )
        )

    def _perform_logout(self) -> None:
        cfg = config.load()
        try:
            api.logout(config.api_server(cfg), config.token(cfg))
        except api.ApiError as e:
            self.notify(str(e), severity="error")
            return
        cfg["token"] = ""
        config.save(cfg)
        # This screen is never popped here — it stays on the stack underneath,
        # same trick as action_change_timezone/action_themes above, so returning
        # from a successful login just pops back down to it directly, keeping
        # the current filter/layout instead of rebuilding the screen from
        # scratch. on_done=self.app.pop_screen is the exact contract
        # LoginWaitScreen/SetupScreen already rely on elsewhere (app.py).
        self.app.push_screen(LoginWaitScreen(config.api_server(cfg), self.app.pop_screen))


class OptionsScreen(Screen):
    """Menu for the settings that used to each have their own footer
    keybinding (timezone, theme, clock, layout) — grouped here under one `o`
    entry so the footer itself stays short. Selecting an entry pops this menu
    first, then runs the matching EventListScreen action, same as it would
    have run directly from its old dedicated key. "Exit" is the one entry
    that doesn't pop first — it quits the whole app, so there's no screen
    left to return to either way. "Login" re-runs the Google login flow on
    demand (e.g. after the JWT expires or a 401 shows up mid-session) without
    needing to log out first; "Logout" stays right below it since the two are
    opposite ends of the same session lifecycle.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        on_timezone: Callable[[], None],
        on_themes: Callable[[], None],
        on_toggle_clock: Callable[[], None],
        on_toggle_layout: Callable[[], None],
        on_login: Callable[[], None],
        on_logout: Callable[[], None],
    ) -> None:
        super().__init__()
        self.on_timezone = on_timezone
        self.on_themes = on_themes
        self.on_toggle_clock = on_toggle_clock
        self.on_toggle_layout = on_toggle_layout
        self.on_login = on_login
        self.on_logout = on_logout

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="options-box"):
                    yield Label("Options", id="options-title")
                    yield OptionList(id="options-list")
        yield Footer()

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.add_options(
            [
                Option("Timezone", id="timezone"),
                Option("Themes", id="themes"),
                Option("Toggle clock on/off", id="clock"),
                Option("Toggle layout (agenda/table)", id="layout"),
                Option("Login", id="login"),
                Option("Logout", id="logout"),
                Option("Exit", id="exit"),
            ]
        )
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id is None:
            return
        if option_id == "exit":
            self.app.exit()
            return
        self.app.pop_screen()
        if option_id == "timezone":
            self.on_timezone()
        elif option_id == "themes":
            self.on_themes()
        elif option_id == "clock":
            self.on_toggle_clock()
        elif option_id == "layout":
            self.on_toggle_layout()
        elif option_id == "login":
            self.on_login()
        elif option_id == "logout":
            self.on_logout()

    def action_cancel(self) -> None:
        self.app.pop_screen()


_ABOUT_TEXT = (
    "Personal project by xyz-leo — Google Calendar, at the terminal. Simple, fast, "
    "distraction-free, since that's where most programmers already spend their day. The web "
    "version brings the same look to any browser, mobile included, without Google's UI in the way."
)


class AboutScreen(Screen):
    """Short project blurb + a clickable link to the repo. Enter opens the link in the
    system browser (clicking it directly also works, same as any other terminal
    hyperlink); Escape goes back."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("enter", "open_link", "Open link in browser")]

    def compose(self) -> ComposeResult:
        # Built as a Text object with an explicit link style, not markup ("[link=...]...[/link]")
        # — Textual's markup parser (distinct from Rich's own, which handles this fine) chokes on
        # a "//" right after the "=" in a link target and raises MarkupError.
        link_text = Text(_REPO_URL, style=f"link {_REPO_URL} underline")
        with Center():
            with Middle():
                with Vertical(id="about-box"):
                    yield Label("About", id="about-title")
                    yield Label(_ABOUT_TEXT, id="about-text")
                    yield Label(link_text, id="about-link")
        yield Footer()

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def action_open_link(self) -> None:
        webbrowser.open(_REPO_URL)


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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Holiday events are merged in from Google's public holiday calendar
        # (read-only, see app/calendar_service.py) — they don't exist on the
        # primary calendar this app writes to, so update/delete would just
        # 404. Hide both from the footer entirely rather than leaving a dead
        # key, same pattern as TimezoneScreen's cancellable flag.
        if action in ("update", "delete") and self.event.get("is_holiday", False):
            return None
        return True

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


class ThemesScreen(Screen):
    """Live-preview picker over every registered theme (built-in + our own)."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="themes-box"):
                    yield Label("Pick a theme", id="themes-title")
                    yield OptionList(id="themes-list")
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
        options.append(Option("Holidays only", id="holidays"))
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
        elif option_id == "holidays":
            self.app.pop_screen()
            # No from/to bound needed — the API itself caps an otherwise-unbounded
            # holiday fetch to the current year (see calendar_service.list_events),
            # so "everything upcoming" here already means "this year's holidays".
            self.on_apply({"only_holidays": True}, "Holidays only")
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


_CALENDAR_WEEKDAYS = "Su Mo Tu We Th Fr Sa"  # matches the Sunday-start weeks below
_CALENDAR = calendar.Calendar(firstweekday=6)


class CalendarScreen(Screen):
    """Month-grid calendar, starting on the current month. Days with an event
    (own or holiday) are colored; Enter on the highlighted day jumps the event
    list straight to it — the exact same (params, label) pair FilterScreen's
    "Pick date..." already produces, via the same on_apply callback.

    Two cursor "modes" share the arrow keys: inside the day grid, Left/Right/
    Up/Down move the highlighted day, and Up from the top row moves the
    cursor onto the month name itself instead of wrapping. Once there,
    Left/Right change month (Down moves back into the grid) — so unlike
    inside the grid, where changing month needs Ctrl+Left/Ctrl+Right
    explicitly, the header is where the plain arrows do it.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "select", "Jump to day"),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("left", "cursor_left", "Left", show=False),
        Binding("right", "cursor_right", "Right", show=False),
        Binding("ctrl+left", "prev_month", "Prev month", show=False),
        Binding("ctrl+right", "next_month", "Next month", show=False),
    ]

    def __init__(self, on_apply: Callable[[dict, str], None]) -> None:
        super().__init__()
        self.on_apply = on_apply
        self._today = datetime.now(self._standard_timezone()).date()
        self._year = self._today.year
        self._month = self._today.month
        self._cursor_mode = "grid"  # or "header"
        self._weeks = self._build_weeks()
        self._cursor_row, self._cursor_col = self._default_cursor()
        self._event_days: set[int] = set()
        self._holiday_days: set[int] = set()

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                with Vertical(id="calendar-box"):
                    yield Static(id="calendar-grid")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_events()
        self._update_grid()

    def _standard_timezone(self) -> ZoneInfo:
        return ZoneInfo(config.timezone(config.load()) or DEFAULT_TIMEZONE)

    def _build_weeks(self) -> list[list[int]]:
        # Each week is 7 ints, 0 for the padding days before the 1st / after
        # the last day of the month — never a real day, never selectable.
        return _CALENDAR.monthdayscalendar(self._year, self._month)

    def _default_cursor(self) -> tuple[int, int]:
        if self._year == self._today.year and self._month == self._today.month:
            for row, week in enumerate(self._weeks):
                if self._today.day in week:
                    return row, week.index(self._today.day)
        return 0, 0

    def _refresh_events(self) -> None:
        # One API call per month shown, filtered to that month's bounds —
        # same bounds _submit_month above already computes for "Pick month...".
        cfg = config.load()
        server = config.api_server(cfg)
        token = config.token(cfg)
        tz = self._standard_timezone()
        last_day = calendar.monthrange(self._year, self._month)[1]
        from_ = datetime(self._year, self._month, 1, tzinfo=tz)
        to = datetime(self._year, self._month, last_day, 23, 59, 59, tzinfo=tz)
        try:
            events = api.fetch_events(
                server, token, params={"from": from_.isoformat(), "to": to.isoformat()}
            )
        except api.ApiError as e:
            self.notify(str(e), severity="error")
            events = []
        self._event_days = set()
        self._holiday_days = set()
        month_prefix = f"{self._year:04d}-{self._month:02d}"
        for event in events:
            day_str = event["start"][:10]
            if day_str[:7] != month_prefix:
                continue  # a timed event near midnight at the month's edge, in a different offset
            day = int(day_str[8:10])
            if event.get("is_holiday"):
                self._holiday_days.add(day)
            else:
                self._event_days.add(day)

    def _update_grid(self) -> None:
        month_label = date(self._year, self._month, 1).strftime("%B %Y").center(20)
        if self._cursor_mode == "header":
            lines = [f"[reverse]{month_label}[/]"]
        else:
            lines = [f"[$accent bold]{month_label}[/]"]
        lines.append(f"[$accent]{_CALENDAR_WEEKDAYS}[/]")
        for row, week in enumerate(self._weeks):
            cells = []
            for col, day in enumerate(week):
                if day == 0:
                    cells.append("  ")
                    continue
                text = f"{day:2d}"
                is_cursor = (
                    self._cursor_mode == "grid" and row == self._cursor_row and col == self._cursor_col
                )
                is_today = (
                    day == self._today.day
                    and self._year == self._today.year
                    and self._month == self._today.month
                )
                if is_cursor:
                    cells.append(f"[reverse]{text}[/]")
                elif day in self._holiday_days:
                    cells.append(f"[#ff6a00]{text}[/]")
                elif day in self._event_days:
                    cells.append(f"[$primary bold]{text}[/]")
                elif is_today:
                    cells.append(f"[$accent bold]{text}[/]")
                else:
                    cells.append(text)
            lines.append(" ".join(cells))
        self.query_one("#calendar-grid", Static).update("\n".join(lines))

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def action_select(self) -> None:
        tz = self._standard_timezone()
        if self._cursor_mode == "header":
            # Same bounds FilterScreen's "Pick month..." already computes —
            # selecting the month name is just another way to filter to the
            # whole displayed month, no day needed.
            last_day = calendar.monthrange(self._year, self._month)[1]
            from_ = datetime(self._year, self._month, 1, tzinfo=tz)
            to = datetime(self._year, self._month, last_day, 23, 59, 59, tzinfo=tz)
            label = date(self._year, self._month, 1).strftime("%B %Y")
            self.app.pop_screen()
            self.on_apply({"from": from_.isoformat(), "to": to.isoformat()}, label)
            return
        day = self._weeks[self._cursor_row][self._cursor_col]
        if day == 0:
            return
        picked = date(self._year, self._month, day)
        from_ = datetime.combine(picked, time.min, tzinfo=tz)
        to = datetime.combine(picked, time.max.replace(microsecond=0), tzinfo=tz)
        label = picked.strftime("%b %-d, %Y").lower()
        self.app.pop_screen()
        self.on_apply({"from": from_.isoformat(), "to": to.isoformat()}, label)

    def action_cursor_up(self) -> None:
        if self._cursor_mode == "grid":
            if self._cursor_row == 0:
                self._cursor_mode = "header"
            else:
                self._cursor_row -= 1
            self._update_grid()

    def action_cursor_down(self) -> None:
        if self._cursor_mode == "header":
            self._cursor_mode = "grid"
        else:
            self._cursor_row = min(self._cursor_row + 1, len(self._weeks) - 1)
        self._update_grid()

    def action_cursor_left(self) -> None:
        if self._cursor_mode == "header":
            self._change_month(-1)
        else:
            self._cursor_col = max(self._cursor_col - 1, 0)
            self._update_grid()

    def action_cursor_right(self) -> None:
        if self._cursor_mode == "header":
            self._change_month(1)
        else:
            self._cursor_col = min(self._cursor_col + 1, 6)
            self._update_grid()

    def action_prev_month(self) -> None:
        self._change_month(-1)

    def action_next_month(self) -> None:
        self._change_month(1)

    def _change_month(self, delta: int) -> None:
        month = self._month + delta
        year = self._year
        if month == 0:
            month, year = 12, year - 1
        elif month == 13:
            month, year = 1, year + 1
        self._year, self._month = year, month
        self._weeks = self._build_weeks()
        self._cursor_row = min(self._cursor_row, len(self._weeks) - 1)
        self._refresh_events()
        self._update_grid()
