"""Общие фикстуры pytest для всех тестов проекта."""

from datetime import datetime

import pytest

from core.database import Database


def gui_available() -> bool:
    """Есть ли дисплей: создаётся ли tkinter.Tk на этой машине.

    GUI-тесты (окно приложения, виджеты) пропускаются целиком, если окно
    создать нельзя (headless-окружение, например CI без экрана).
    """
    import tkinter as tk

    try:
        probe = tk.Tk()
        probe.withdraw()
        probe.destroy()
        return True
    except tk.TclError:
        return False


@pytest.fixture
def db() -> Database:
    """База на in-memory SQLite — реальный файл БД не затрагивается."""
    return Database(path=":memory:")


@pytest.fixture
def frozen_now(monkeypatch):
    """Заморозить core.database.datetime так, чтобы now() возвращала fake_now.

    Реальный код вызывает datetime.now() и strptime(); подмена сохраняет
    strptime от настоящего класса.
    """

    def _freeze(fake_now: datetime) -> None:
        class _FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_now

        monkeypatch.setattr("core.database.datetime", _FakeDatetime)

    return _freeze
