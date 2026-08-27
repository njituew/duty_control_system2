"""Настройка логирования для приложения и сырых данных камеры."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_logs_dir() -> Path:
    """Возвращает директорию logs рядом с exe (в сборке) или в корне проекта."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    logs_dir = base / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def setup_logging() -> tuple[logging.Logger, logging.Logger]:
    """Настраивает логирование:
    - root logger: логи приложения в консоль (dev) и app.log (INFO+)
    - camera.raw: сырые данные от камеры в camera_raw.log (DEBUG+)
    Возвращает кортеж (root_logger, camera_logger).
    """
    logs_dir = get_logs_dir()

    # Форматтеры
    app_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    camera_formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Root logger — для всего приложения
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Файловый хендлер для приложения (ротация 5 МБ, 5 файлов)
    app_handler = RotatingFileHandler(
        logs_dir / "app.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setFormatter(app_formatter)
    app_handler.setLevel(logging.INFO)
    root_logger.addHandler(app_handler)

    # Консольный хендлер для разработки
    if not getattr(sys, "frozen", False):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(app_formatter)
        console_handler.setLevel(logging.INFO)
        root_logger.addHandler(console_handler)

    # Логгер камеры — только файл, сырые данные, не пускаем в root
    camera_logger = logging.getLogger("camera.raw")
    camera_logger.setLevel(logging.DEBUG)
    camera_logger.propagate = False

    camera_handler = RotatingFileHandler(
        logs_dir / "camera_raw.log",
        maxBytes=20_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    camera_handler.setFormatter(camera_formatter)
    camera_handler.setLevel(logging.DEBUG)
    camera_logger.addHandler(camera_handler)

    return root_logger, camera_logger


def get_app_logger() -> logging.Logger:
    """Получить root логгер (создаёт при первом вызове)."""
    logger = logging.getLogger()
    if not logger.handlers:
        setup_logging()
    return logger


def get_camera_logger() -> logging.Logger:
    """Получить логгер сырых данных камеры (создаёт при первом вызове)."""
    logger = logging.getLogger("camera.raw")
    if not logger.handlers:
        setup_logging()
    return logger