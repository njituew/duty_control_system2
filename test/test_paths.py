"""Тесты путей приложения: core.paths."""

import sys
from pathlib import Path

import core.paths as paths_module
from core.paths import app_base_dir, app_data_dir


def test_app_base_dir_dev() -> None:
    """В dev-режиме база — корень проекта (два уровня вверх от paths.py)."""
    assert app_base_dir() == str(Path(__file__).resolve().parent.parent)


def test_app_base_dir_frozen(monkeypatch) -> None:
    """В PyInstaller-сборке база — каталог рядом с exe."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/app/dcs.exe")
    assert app_base_dir() == "/opt/app"


def test_app_data_dir_creates_directory(monkeypatch, tmp_path) -> None:
    """app_data_dir() создаёт подкаталог database и возвращает его путь."""
    monkeypatch.setattr(paths_module, "app_base_dir", lambda: str(tmp_path))

    result = app_data_dir()

    assert result == str(tmp_path / "database")
    assert Path(result).is_dir()
    # Повторный вызов идемпотентен.
    assert app_data_dir() == result
