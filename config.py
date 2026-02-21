"""Конфигурация приложения: цвета, статусы, маппинги."""

import os
import sys
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def _get_db_path() -> str:
    """Путь к БД: рядом с .exe или рядом с main.py."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "database.db")


DB_PATH = _get_db_path()

# Цветовая палитра
C: dict[str, str] = {
    "bg": "#0f1117",
    "surface": "#1a1d27",
    "card": "#1e2130",
    "border": "#2a2d3e",
    "accent": "#4f8ef7",
    "accent_h": "#6ba3ff",
    "green": "#3dd68c",
    "red": "#f75f5f",
    "yellow": "#f7c948",
    "text": "#e8eaf0",
    "subtext": "#6b7080",
    "idle": "#6b7080",
    "arrived": "#3dd68c",
    "departed": "#f75f5f",
}

# Маппинги статусов и событий
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

# Порядок переключения статусов
STATUS_ORDER: list[str] = ["idle", "arrived", "departed"]
