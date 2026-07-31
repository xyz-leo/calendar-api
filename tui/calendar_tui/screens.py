from typing import Callable

from textual.app import ComposeResult
from textual.containers import Center, Middle
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label

from . import api, config


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
                yield Label(self.prompt, id="setup-prompt")
                yield Input(placeholder=self.placeholder, id="setup-input")

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


class EventListScreen(Screen):
    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="events")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Start", "Summary", "Location")
        table.cursor_type = "row"
        self.action_refresh()

    def action_refresh(self) -> None:
        cfg = config.load()
        server = config.api_server(cfg)
        token = config.token(cfg)
        table = self.query_one(DataTable)
        table.clear()
        try:
            events = api.fetch_events(server, token)
        except api.ApiError as e:
            self.notify(str(e), severity="error")
            return
        for event in events:
            table.add_row(event["start"], event["summary"], event.get("location") or "")
