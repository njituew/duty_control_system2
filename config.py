"""Application configuration: colors, statuses, and label mappings."""

import os
import sys

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def _get_db_path() -> str:
    """Return the absolute path to the SQLite database file.

    The database lives in a 'database' subfolder. When running as a
    PyInstaller bundle that folder sits next to the executable; during
    development it sits next to this source file. The folder is created
    on first access if it does not exist yet.
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    db_dir = os.path.join(base, "database")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "database.db")


DB_PATH = _get_db_path()

# How many calendar months of event history to keep.
# Purge runs lazily on every status change.
EVENT_RETENTION_MONTHS: int = 1

# Camera (ANPR) integration. Credentials live in camera_settings.py, which is
# gitignored -- copy that file manually to any new machine.
try:
    from camera_settings import CAMERA_HOST, CAMERA_PASSWORD, CAMERA_USER
except ImportError:
    CAMERA_HOST = CAMERA_USER = CAMERA_PASSWORD = ""

# Event codes to subscribe to via eventManager.cgi?action=attach.
CAMERA_EVENT_CODES: list[str] = ["TrafficJunction"]

# How often the UI checks the camera event queue, in milliseconds.
CAMERA_QUEUE_POLL_MS: int = 500

# Single-palette, disciplined token set:
# cool graphite neutrals (near-black, never pure black) + one restrained
# amber accent. Status colors are semantic, desaturated, used sparingly.
C: dict[str, str] = {
    "bg": "#0b0c0e",
    "surface": "#131519",
    "card": "#191c21",
    "border": "#2a2d33",
    "accent": "#d9a24a",
    "accent_h": "#e8b766",
    "green": "#39bd84",
    "red": "#d4705f",
    "yellow": "#d8b24a",
    "text": "#e7e9ec",
    "subtext": "#8b909a",
    "idle": "#5c616b",
    "arrived": "#39bd84",
    "departed": "#d4705f",
}

# Corner-radius scale (Shape Consistency Lock):
# controls (buttons/entries) = 6px, surfaces (panels/cards) = 0px, nav rail = 0px.
CTRL_RADIUS: int = 6

# (bullet symbol, hex color, human-readable label) per status key
STATUS_MAP: dict[str, tuple[str, str, str]] = {
    "idle": ("●", C["idle"], "В ожидании"),
    "arrived": ("▲", C["arrived"], "Прибыл"),
    "departed": ("▼", C["departed"], "Убыл"),
}

EVENT_LABELS: dict[str, str] = {
    "arrived": "Прибыл",
    "departed": "Убыл",
    "created": "Создан",
    "deleted": "Удалён",
}

TYPE_LABELS: dict[str, str] = {
    "vehicle": "ТС",
    "commander": "Командир",
}

EVENT_COLORS: dict[str, str] = {
    "arrived": C["arrived"],
    "departed": C["departed"],
    "created": C["accent"],
    "deleted": C["red"],
}

# Click cycles only between arrived and departed.
# "idle" is the creation-only state and is excluded from the toggle loop.
STATUS_ORDER: list[str] = ["arrived", "departed"]
