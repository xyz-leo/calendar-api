import json

from textual.theme import Theme

from .config import CONFIG_DIR

THEME_FILE = CONFIG_DIR / "theme.json"

# Near-black background, white body text, gold for small accents/titles, ruby
# red as the primary list/selection/border color — modeled on a neovim
# colorscheme reference. Fixed hex colors (no terminal inheritance). This is
# only ever used to seed theme.json on first boot — after that, the file on
# disk is the source of truth.
DEFAULT_THEME = {
    "name": "calendar-tui",
    "dark": True,
    "ansi": False,
    "primary": "#a62639",
    "secondary": "#7a1c2b",
    "accent": "#d4af37",
    "warning": "#d4af37",
    "error": "#e0616e",
    "success": "#d4af37",
    "foreground": "#ececec",
    "background": "#0d0d0d",
    "surface": "#131313",
    "panel": "#1c1717",
    "variables": {},
}

# "ansi_default" inherits whatever the terminal itself is set to — used here
# only for the two safety variables Textual's own Screen CSS references
# unconditionally whenever a theme has ansi=True (regardless of whether inline
# mode is actually used; omitting them fails CSS parsing at startup).
_ANSI_SAFETY_VARIABLES = {
    "ansi-background": "ansi_default",
    "ansi-foreground": "ansi_default",
}

# Same palette as DEFAULT_THEME, byte-for-byte — only the background/surface/
# panel differ (transparent, inheriting the terminal, instead of fixed near-
# black). Registered under the built-in "ansi-dark" name in app.py, replacing
# Textual's own version outright.
ANSI_DARK_THEME = {
    **DEFAULT_THEME,
    "name": "ansi-dark",
    "ansi": True,
    "background": "ansi_default",
    "surface": "ansi_default",
    "panel": "ansi_default",
    "variables": _ANSI_SAFETY_VARIABLES,
}

# Same idea, but for a light terminal: the ruby/gold accents carry over
# unchanged, but foreground/panel invert for legibility against a light
# background — reusing DEFAULT_THEME's white foreground here would be
# unreadable once the background is actually light instead of near-black.
ANSI_LIGHT_THEME = {
    **DEFAULT_THEME,
    "name": "ansi-light",
    "dark": False,
    "ansi": True,
    "foreground": "#1a1a1a",
    "background": "ansi_default",
    "surface": "ansi_default",
    "panel": "ansi_default",
    "variables": _ANSI_SAFETY_VARIABLES,
}


# Vivid synthwave pairing: neon purple as the primary/structural color
# (borders, headers, selection), neon green as the accent (titles) — near-
# black background with a slight purple tint so the neon tones pop.
NEON_PURPLE_THEME = {
    "name": "neon-purple",
    "dark": True,
    "ansi": False,
    "primary": "#b026ff",
    "secondary": "#ff2e88",
    "accent": "#39ff14",
    "warning": "#39ff14",
    "error": "#ff0055",
    "success": "#39ff14",
    "foreground": "#f0f0f0",
    "background": "#0d0614",
    "surface": "#150b22",
    "panel": "#1f1030",
    "variables": {},
}

# Vivid neon yellow as the primary/structural color, neon magenta as the
# accent (titles) for contrast — near-black background with a slight warm
# tint.
NEON_YELLOW_THEME = {
    "name": "neon-yellow",
    "dark": True,
    "ansi": False,
    "primary": "#ffee00",
    "secondary": "#ff9500",
    "accent": "#ff00aa",
    "warning": "#ffee00",
    "error": "#ff0055",
    "success": "#ffee00",
    "foreground": "#f5f5f0",
    "background": "#100e08",
    "surface": "#1a1710",
    "panel": "#26210f",
    "variables": {},
}


def load() -> dict:
    if not THEME_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        THEME_FILE.write_text(json.dumps(DEFAULT_THEME, indent=2) + "\n")
        return dict(DEFAULT_THEME)
    # Missing keys fall back to defaults so a partially-edited file (or one saved
    # by an older version with fewer fields) never crashes the app.
    return {**DEFAULT_THEME, **json.loads(THEME_FILE.read_text())}


def _theme_from(data: dict) -> Theme:
    return Theme(
        name=data["name"],
        dark=data["dark"],
        primary=data["primary"],
        secondary=data["secondary"],
        warning=data["warning"],
        error=data["error"],
        success=data["success"],
        accent=data["accent"],
        foreground=data["foreground"],
        background=data["background"],
        surface=data["surface"],
        panel=data["panel"],
        ansi=data["ansi"],
        variables=data["variables"],
    )


def build() -> Theme:
    """The user's custom, editable theme (~/.config/calendar-tui/theme.json)."""
    return _theme_from(load())


def build_ansi_dark() -> Theme:
    """Recolored replacement for Textual's built-in "ansi-dark" theme."""
    return _theme_from(ANSI_DARK_THEME)


def build_ansi_light() -> Theme:
    """Recolored replacement for Textual's built-in "ansi-light" theme."""
    return _theme_from(ANSI_LIGHT_THEME)


def build_neon_purple() -> Theme:
    return _theme_from(NEON_PURPLE_THEME)


def build_neon_yellow() -> Theme:
    return _theme_from(NEON_YELLOW_THEME)
