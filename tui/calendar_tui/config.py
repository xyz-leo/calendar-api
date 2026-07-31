import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "calendar-tui"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def api_server(config: dict) -> str | None:
    return os.environ.get("CALENDAR_API_SERVER") or config.get("api_server")


def token(config: dict) -> str | None:
    return os.environ.get("CALENDAR_TOKEN") or config.get("token")
