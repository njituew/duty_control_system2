"""Сохранение учётных данных камеры.
Параметры сохраняются в database/camera_settings.json"""

import json
import os

from core.paths import app_data_dir

CONFIG_FILENAME = "camera_settings.json"

EMPTY_SETTINGS: dict[str, str] = {
    "host": "",
    "user": "",
    "password": "",
}


def _get_config_path() -> str:
    """Абсолютный путь к файлу настроек камеры в подпапке database."""
    return os.path.join(app_data_dir(), CONFIG_FILENAME)


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
