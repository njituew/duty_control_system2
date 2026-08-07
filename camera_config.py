"""Сохранение учётных данных камеры.

Параметры подключения сохраняются в JSON-файл в подпапке database.
Модуль хранит только параметры подключения — никаких лишних данных.
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
    """Абсолютный путь к файлу настроек камеры в подпапке database."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    db_dir = os.path.join(base, "database")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, CONFIG_FILENAME)


def load_settings() -> dict[str, str]:
    """Загрузить сохранённые учётные данные; при ошибке вернуть пустые значения."""
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
    """Сохранить учётные данные камеры в файл настроек."""
    path = _get_config_path()
    data = {"host": host, "user": user, "password": password}
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise RuntimeError(f"Не удалось сохранить настройки камеры: {exc}") from exc
