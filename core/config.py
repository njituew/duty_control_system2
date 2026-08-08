"""Конфигурация приложения: цвета, статусы и подписи."""

import os

import customtkinter as ctk

from core.paths import app_data_dir

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


DB_PATH = os.path.join(app_data_dir(), "database.db")

# Сколько календарных месяцев истории событий хранить.
# Очистка выполняется лениво при каждой смене статуса.
EVENT_RETENTION_MONTHS: int = 1

# Учётные данные камеры задаются из UI и сохраняются в core/camera_settings.py,
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
    "danger_h": "#241a1a",
    "yellow": "#d8b24a",
    "text": "#e7e9ec",
    "subtext": "#8b909a",
    "idle": "#5c616b",
    "arrived": "#39bd84",
    "departed": "#d4705f",
}

# Скругление углов: элементы управления (кнопки/поля) 6px, панели 0px.
CTRL_RADIUS: int = 6

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

# Единый источник статусов: набор и цикл переключения.
# Клик переключает только между arrived/departed; "idle" — состояние
# при создании и из цикла переключения исключён.
STATUS_ORDER: list[str] = ["arrived", "departed"]
STATUS_ALL: frozenset[str] = frozenset({"idle", *STATUS_ORDER})


def next_status(current: str) -> str:
    """Следующий статус по циклу кликов.

    Статус из STATUS_ORDER сдвигается по кругу; любой другой статус
    (например 'idle') переводится в первый статус цикла.
    """
    if current in STATUS_ORDER:
        idx = STATUS_ORDER.index(current)
        return STATUS_ORDER[(idx + 1) % len(STATUS_ORDER)]
    return STATUS_ORDER[0]
