"""Persistent storage for camera connection credentials.

Credentials are saved to a plain JSON file next to the application (next to the
executable when bundled with PyInstaller, otherwise next to this source file).
The file holds only connection parameters -- this module deliberately does not
store any sensitive data beyond the password the user types in.
"""

import json
import os
import sys

CONFIG_FILENAME = "camera_settings.json"

EMPTY_SETTINGS: dict[str, str] = {
    "host": "",
    "user": "",
    "password": "",
}


def _get_config_path() -> str:
    """Return the absolute path to the persisted camera settings file.

    The file lives in the 'database' subfolder alongside the SQLite database.
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    db_dir = os.path.join(base, "database")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, CONFIG_FILENAME)


def load_settings() -> dict[str, str]:
    """Load saved camera credentials, or a dict of empty strings on any failure."""
    path = _get_config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return dict(EMPTY_SETTINGS)
    if not isinstance(data, dict):
        return dict(EMPTY_SETTINGS)
    return {
        "host": str(data.get("host", "")),
        "user": str(data.get("user", "")),
        "password": str(data.get("password", "")),
    }


def save_settings(host: str, user: str, password: str) -> None:
    """Persist the given camera credentials to the settings file."""
    path = _get_config_path()
    data = {"host": host, "user": user, "password": password}
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise RuntimeError(f"Не удалось сохранить настройки камеры: {exc}") from exc
