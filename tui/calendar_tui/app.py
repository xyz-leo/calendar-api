from textual.app import App

from . import config
from .screens import EventListScreen, SetupScreen


class CalendarTUI(App):
    TITLE = "calendar-tui"

    def on_mount(self) -> None:
        self.push_screen(self._next_screen())

    def _next_screen(self) -> SetupScreen | EventListScreen:
        cfg = config.load()
        if not config.api_server(cfg):
            return SetupScreen(
                "api_server",
                "Type the API server to use (e.g. http://localhost:8000)",
                "http://localhost:8000",
                self._advance,
            )
        if not config.token(cfg):
            return SetupScreen(
                "token",
                "Paste your API token (get one with: calctl.sh token)",
                "eyJ...",
                self._advance,
            )
        return EventListScreen()

    def _advance(self) -> None:
        self.pop_screen()
        self.push_screen(self._next_screen())


def run() -> None:
    CalendarTUI().run()


if __name__ == "__main__":
    run()
