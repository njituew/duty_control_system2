"""Конфигурация приложения: цвета, статусы и подписи."""

import os
import sys

import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def _get_db_path() -> str:
    """Вернуть абсолютный путь к файлу SQLite-базы в подпапке database."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    db_dir = os.path.join(base, "database")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "database.db")


DB_PATH = _get_db_path()

# Сколько календарных месяцев истории событий хранить.
# Очистка выполняется лениво при каждой смене статуса.
EVENT_RETENTION_MONTHS: int = 1

# Учётные данные камеры задаются из UI и сохраняются в camera_config.py,
# а не задаются жёстко здесь.

# Коды событий для подписки через eventManager.cgi?action=attach.
CAMERA_EVENT_CODES: list[str] = ["TrafficJunction"]

# Как часто UI опрашивает очередь событий камеры, мс.
CAMERA_QUEUE_POLL_MS: int = 500

# Палитра: тёмные нейтральные оттенки + один янтарный акцент.
# Цвета статусов смысловые, приглушённые, используются умеренно.
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

# Скругление углов: элементы управления (кнопки/поля) 6px, панели 0px.
CTRL_RADIUS: int = 6

# (символ, цвет, подпись) для каждого статуса
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

# Клик переключает только между arrived/departed; "idle" — состояние
# при создании и из цикла переключения исключён.
STATUS_ORDER: list[str] = ["arrived", "departed"]
