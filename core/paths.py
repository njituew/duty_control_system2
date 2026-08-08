"""Каталоги приложения: единый источник путей для dev и PyInstaller-сборки."""

import os
import sys

# Подкаталог данных приложения (БД и настройки камеры).
APP_DATA_DIR = "database"


def app_base_dir() -> str:
    """Базовый каталог приложения: рядом с exe в сборке, иначе корень проекта."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_data_dir() -> str:
    """Каталог данных приложения; создаётся при необходимости."""
    path = os.path.join(app_base_dir(), APP_DATA_DIR)
    os.makedirs(path, exist_ok=True)
    return path
