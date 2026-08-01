from textual.app import App

from . import config, theme as theme_module
from .screens import EventListScreen, LoginChoiceScreen, SetupScreen, TimezoneScreen


class CalendarTUI(App):
    TITLE = "calendar-tui"
    CSS_PATH = "app.tcss"

    def on_mount(self) -> None:
        theme = theme_module.build()
        self.register_theme(theme)
        # Replace Textual's built-in ansi-dark/ansi-light outright, rather than
        # registering under different names — they're the same idea (inherit
        # the terminal's transparent background), just recolored to match.
        self.register_theme(theme_module.build_ansi_dark())
        self.register_theme(theme_module.build_ansi_light())
        self.register_theme(theme_module.build_neon_purple())
        self.register_theme(theme_module.build_neon_yellow())
        cfg = config.load()
        wanted = config.active_theme(cfg)
        self.theme = wanted if wanted in self.available_themes else theme.name
        self.push_screen(self._next_screen())

    def _next_screen(self) -> SetupScreen | LoginChoiceScreen | TimezoneScreen | EventListScreen:
        cfg = config.load()
        if not config.api_server(cfg):
            return SetupScreen(
                "api_server",
                "Type the API server to use (e.g. http://localhost:8088)",
                "http://localhost:8088",
                self._advance,
            )
        if not config.timezone(cfg):
            return TimezoneScreen(self._advance, cancellable=False)
        if not config.token(cfg):
            return LoginChoiceScreen(config.api_server(cfg), self._advance)
        return EventListScreen()

    def _advance(self) -> None:
        self.pop_screen()
        self.push_screen(self._next_screen())


def run() -> None:
    CalendarTUI().run()


if __name__ == "__main__":
    run()
