"""Тесты очистки событий по скользящему окну (in-memory SQLite).

Проверяет:
1. Арифметику _cutoff_ts — ровно 1 календарный месяц назад с переносом года,
   ограничением по короткому месяцу и високосному февралю.
2. Границы очистки — удаляются только события строго старше cutoff.
3. Переход года сквозным прогоном через Database.update_status_and_log.
4. Атомарность — при ошибке очистки БД откатывается целиком.
"""

import sqlite3
from datetime import datetime, timezone

import pytest

from core.database import Database, DatabaseError, _cutoff_ts

# Вспомогательные функции — пишут события напрямую, в обход публичного API.


def _insert_event(
    db: Database, ts: str, event_type: str = "arrived", name: str = "Тест"
) -> None:
    db._conn.execute(
        "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
        "VALUES ('vehicle', 1, ?, ?, ?)",
        (name, event_type, ts),
    )
    db._conn.commit()


def _count_events(db: Database) -> int:
    return db._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def _all_ts(db: Database) -> list[str]:
    rows = db._conn.execute("SELECT ts FROM events ORDER BY ts").fetchall()
    return [r[0] for r in rows]


CUTOFF_CASES = [
    # (поддельное now, ожидаемый префикс даты cutoff)
    ("2027-01-15 10:00:00", "2026-12-15"),  # переход года
    ("2027-01-01 00:00:00", "2026-12-01"),  # 1 января → 1 декабря
    ("2026-03-31 23:59:59", "2026-02-28"),  # 31 марта → 28 февраля
    ("2026-03-15 08:30:00", "2026-02-15"),  # обычный случай
    ("2026-12-31 12:00:00", "2026-11-30"),  # 31 декабря → 30 ноября
    ("2024-03-31 00:00:00", "2024-02-29"),  # високосный 2024
    ("2026-02-28 00:00:00", "2026-01-28"),  # февраль → январь
]


@pytest.mark.parametrize("fake_now_str,expected_prefix", CUTOFF_CASES)
def test_cutoff_arithmetic(fake_now_str: str, expected_prefix: str, frozen_now) -> None:
    fake_now = datetime.strptime(fake_now_str, "%Y-%m-%d %H:%M:%S").astimezone()
    frozen_now(fake_now)

    result = _cutoff_ts(1)

    assert result.startswith(expected_prefix)


PURGE_SCENARIOS = [
    pytest.param(
        "2027-01-15 10:00:00",  # cutoff = 2026-12-15 00:00:00
        [
            "2026-12-14 23:59:59",  # за секунду до cutoff
            "2026-11-01 00:00:00",  # два месяца назад
            "2026-06-15 12:00:00",  # полгода назад
        ],
        [
            "2026-12-15 00:00:00",  # ровно на границе cutoff
            "2026-12-15 00:00:01",  # через секунду после cutoff
            "2027-01-10 08:00:00",  # недавнее
        ],
        id="year-rollover",
    ),
    pytest.param(
        "2026-03-31 12:00:00",  # cutoff = 2026-02-28 00:00:00
        [
            "2026-02-27 23:59:59",
            "2026-01-15 00:00:00",
        ],
        [
            "2026-02-28 00:00:00",  # ровно на ограниченном cutoff
            "2026-03-01 00:00:00",
            "2026-03-31 11:00:00",
        ],
        id="short-month",
    ),
    pytest.param(
        "2024-03-31 12:00:00",  # cutoff = 2024-02-29 00:00:00 (високосный)
        [
            "2024-02-28 23:59:59",
            "2024-01-01 00:00:00",
        ],
        [
            "2024-02-29 00:00:00",
            "2024-03-15 00:00:00",
        ],
        id="leap-year",
    ),
]


@pytest.mark.parametrize("fake_now_str,should_delete,should_keep", PURGE_SCENARIOS)
def test_purge_boundary(
    db: Database,
    frozen_now,
    fake_now_str: str,
    should_delete: list[str],
    should_keep: list[str],
) -> None:
    for ts in should_delete + should_keep:
        _insert_event(db, ts)

    frozen_now(datetime.strptime(fake_now_str, "%Y-%m-%d %H:%M:%S").astimezone())
    db._purge_old_events()
    db._conn.commit()

    remaining = set(_all_ts(db))
    survived = set(should_delete) & remaining
    assert not survived, f"должны были быть удалены, но остались: {survived}"
    assert set(should_keep) <= remaining, (
        f"не должны были быть удалены: {set(should_keep) - remaining}"
    )


def test_year_rollover_e2e(db: Database, frozen_now) -> None:
    """Сквозной прогон через реальный публичный метод update_status_and_log."""
    vid = db.add_vehicle("А001АА")

    old_ts = "2026-12-14 10:00:00"  # должно быть удалено (до 2026-12-15)
    keep_ts = "2026-12-15 00:00:00"  # должно сохраниться (на границе cutoff)
    _insert_event(db, old_ts, name="А001АА")
    _insert_event(db, keep_ts, name="А001АА")

    frozen_now(datetime(2027, 1, 15, 9, 0, 0, tzinfo=timezone.utc))
    db.update_status_and_log("vehicle", vid, "А001АА", "arrived")

    after_ts = _all_ts(db)
    assert old_ts not in after_ts
    assert keep_ts in after_ts

    # Новое событие, записанное update_status_and_log, должно присутствовать.
    assert any(ts.startswith("2027-01-15") for ts in after_ts)


def test_atomicity_on_error(db: Database, monkeypatch) -> None:
    vid = db.add_vehicle("Б002ББ")
    _insert_event(db, "2020-01-01 00:00:00", name="Б002ББ")  # старое, подлежит очистке
    before = _count_events(db)

    # Заставляем _purge_old_events упасть, чтобы откатилась вся транзакция.
    def broken_purge() -> None:
        raise sqlite3.OperationalError("simulated disk error")

    monkeypatch.setattr(db, "_purge_old_events", broken_purge)

    with pytest.raises(DatabaseError):
        db.update_status_and_log("vehicle", vid, "Б002ББ", "arrived")

    assert _count_events(db) == before
