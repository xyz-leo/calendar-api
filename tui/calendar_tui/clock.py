from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

# 5-pixel-row, 3-column digit bitmaps — plain rectangular segments only (no
# partial/diagonal fill), for a squared-off look rather than a rounded one.
_DIGIT_BITMAPS = {
    "0": ["███", "█ █", "█ █", "█ █", "███"],
    "1": ["  █", "  █", "  █", "  █", "  █"],
    "2": ["███", "  █", "███", "█  ", "███"],
    "3": ["███", "  █", "███", "  █", "███"],
    "4": ["█ █", "█ █", "███", "  █", "  █"],
    "5": ["███", "█  ", "███", "  █", "███"],
    "6": ["███", "█  ", "███", "█ █", "███"],
    "7": ["███", "  █", "  █", "  █", "  █"],
    "8": ["███", "█ █", "███", "█ █", "███"],
    "9": ["███", "█ █", "███", "  █", "███"],
    ":": [" ", "█", " ", "█", " "],
}


def _compress(bitmap: list[str]) -> list[str]:
    """Pack a 5-pixel-row bitmap into 3 text rows with half-block characters,
    for a shorter, wider look instead of a tall, narrow one — each text cell
    covers 2 pixel-rows (top half / bottom half / both / neither)."""
    rows = bitmap if len(bitmap) % 2 == 0 else [*bitmap, " " * len(bitmap[0])]
    lines = []
    for top, bottom in zip(rows[0::2], rows[1::2]):
        line = "".join(
            "█" if t != " " and b != " " else "▀" if t != " " else "▄" if b != " " else " "
            for t, b in zip(top, bottom)
        )
        lines.append(line)
    return lines


_DIGITS = {char: _compress(bitmap) for char, bitmap in _DIGIT_BITMAPS.items()}
_DIGIT_HEIGHT = len(next(iter(_DIGITS.values())))


class Clock(Vertical):
    """A small, square-block live clock plus today's date. Local system time."""

    def compose(self) -> ComposeResult:
        yield Static(id="clock-time")
        yield Static(id="clock-date")

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(1, self._tick)

    def _tick(self) -> None:
        now = datetime.now()
        time_text = now.strftime("%H:%M:%S")
        lines = [" ".join(_DIGITS[char][row] for char in time_text) for row in range(_DIGIT_HEIGHT)]
        self.query_one("#clock-time", Static).update("\n".join(lines))
        self.query_one("#clock-date", Static).update(now.strftime("%a, %B %-d, %Y").lower())
