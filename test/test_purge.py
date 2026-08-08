"""Смоук-тест очистки событий по скользящему окну.

Работает на изолированной БД в памяти — реальная database/database.db не трогается.

Проверяет:
1. Границы — удаляются только события старше ровно 1 календарного месяца.
2. Переход года — события до границы удаляются, на границе и позже остаются.
3. Короткий месяц — очистка 2026-03-31 корректно сводится к 28 февраля.
4. Сквозной прогон через Database.update_status_and_log.
"""

import sqlite3
import sys
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, ".")

from core.database import Database, _cutoff_ts
from harness import fail, ok, section, summarize

# Вспомогательные функции


def _make_db() -> Database:
    """Вернуть Database на in-memory SQLite — реальная БД не затрагивается."""
    return Database(path=":memory:")


def _insert_event(
    db: Database, ts: str, event_type: str = "arrived", name: str = "Тест"
) -> None:
    """Записать сырое событие с произвольным ts в обход публичного API."""
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


# Тест 1 — арифметика _cutoff_ts


def test_cutoff_arithmetic() -> None:
    section("TEST 1 · _cutoff_ts calendar arithmetic")

    cases = [
        # (поддельное now, ожидаемый префикс даты cutoff)
        ("2027-01-15 10:00:00", "2026-12-15"),  # переход года
        ("2027-01-01 00:00:00", "2026-12-01"),  # 1 января → 1 декабря
        ("2026-03-31 23:59:59", "2026-02-28"),  # 31 марта → 28 февраля
        ("2026-03-15 08:30:00", "2026-02-15"),  # обычный случай
        ("2026-12-31 12:00:00", "2026-11-30"),  # 31 декабря → 30 ноября
        ("2024-03-31 00:00:00", "2024-02-29"),  # високосный 2024
        ("2026-02-28 00:00:00", "2026-01-28"),  # февраль → январь
    ]

    all_ok = True
    for fake_now_str, expected_prefix in cases:
        fake_now = datetime.strptime(fake_now_str, "%Y-%m-%d %H:%M:%S")
        with patch("core.database.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime
            result = _cutoff_ts(1)

        passed = result.startswith(expected_prefix)
        label = f"now={fake_now_str}  →  cutoff starts with {expected_prefix}  (got {result[:10]})"
        if passed:
            ok(label)
        else:
            fail(label)
            all_ok = False

    return all_ok


# Тест 2 — границы: удаляются только строки строго старше cutoff


def test_purge_boundary() -> None:
    section("TEST 2 · Purge boundary — keeps events on cutoff date, deletes older")

    db = _make_db()

    # Поддельное "сегодня" = 2027-01-15 → cutoff = 2026-12-15 00:00:00
    fake_now = datetime(2027, 1, 15, 10, 0, 0)

    # События, которые ДОЛЖНЫ быть удалены (ts < cutoff)
    should_delete = [
        "2026-12-14 23:59:59",  # за секунду до cutoff
        "2026-11-01 00:00:00",  # два месяца назад
        "2026-06-15 12:00:00",  # полгода назад
    ]
    # События, которые ДОЛЖНЫ сохраниться (ts >= cutoff)
    should_keep = [
        "2026-12-15 00:00:00",  # ровно на границе cutoff
        "2026-12-15 00:00:01",  # через секунду после cutoff
        "2027-01-10 08:00:00",  # недавнее
    ]

    for ts in should_delete + should_keep:
        _insert_event(db, ts)

    assert _count_events(db) == len(should_delete) + len(should_keep)

    with patch("core.database.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.strptime = datetime.strptime
        db._purge_old_events()
        db._conn.commit()

    remaining = set(_all_ts(db))
    all_ok = True

    for ts in should_delete:
        if ts in remaining:
            fail(f"Should have been deleted but survived: {ts}")
            all_ok = False
        else:
            ok(f"Correctly deleted:  {ts}")

    for ts in should_keep:
        if ts not in remaining:
            fail(f"Should have survived but was deleted: {ts}")
            all_ok = False
        else:
            ok(f"Correctly kept:     {ts}")

    return all_ok


# Тест 3 — переход года сквозным запуском (реальный публичный метод)


def test_year_rollover_e2e() -> None:
    section("TEST 3 · Year rollover via update_status_and_log (end-to-end)")

    db = _make_db()

    # Добавляем реальное ТС, чтобы было что обновлять.
    vid = db.add_vehicle("А001АА")

    # Старые события вставляем напрямую — до поддельного "сегодня".
    fake_today = datetime(2027, 1, 15, 9, 0, 0)
    old_ts = "2026-12-14 10:00:00"  # должно быть удалено (до 2026-12-15)
    keep_ts = "2026-12-15 00:00:00"  # должно сохраниться (на границе cutoff)

    _insert_event(db, old_ts, name="А001АА")
    _insert_event(db, keep_ts, name="А001АА")

    before = _count_events(db)

    with patch("core.database.datetime") as mock_dt:
        mock_dt.now.return_value = fake_today
        mock_dt.strptime = datetime.strptime
        # Вызов реального публичного метода — очистка запускается внутри транзакции.
        db.update_status_and_log("vehicle", vid, "А001АА", "arrived")

    after_ts = _all_ts(db)
    all_ok = True

    if old_ts in after_ts:
        fail(f"Old event was NOT deleted: {old_ts}")
        all_ok = False
    else:
        ok(f"Old event deleted correctly: {old_ts}")

    if keep_ts not in after_ts:
        fail(f"Boundary event was wrongly deleted: {keep_ts}")
        all_ok = False
    else:
        ok(f"Boundary event kept correctly: {keep_ts}")

    # Новое событие, записанное update_status_and_log, должно присутствовать.
    new_events = [ts for ts in after_ts if ts.startswith("2027-01-15")]
    if new_events:
        ok(f"New event written correctly: {new_events[0]}")
    else:
        fail("New event from update_status_and_log is missing")
        all_ok = False

    return all_ok


# Тест 4 — короткий месяц (31 марта → 28 февраля)


def test_short_month_edge_case() -> None:
    section("TEST 4 · Short-month edge case (31 Mar → clamp to 28 Feb)")

    db = _make_db()
    fake_today = datetime(2026, 3, 31, 12, 0, 0)

    # cutoff = 2026-02-28 00:00:00 (в феврале нет 31-го числа)
    should_delete = [
        "2026-02-27 23:59:59",
        "2026-01-15 00:00:00",
    ]
    should_keep = [
        "2026-02-28 00:00:00",  # ровно на ограниченном cutoff
        "2026-03-01 00:00:00",
        "2026-03-31 11:00:00",
    ]

    for ts in should_delete + should_keep:
        _insert_event(db, ts)

    with patch("core.database.datetime") as mock_dt:
        mock_dt.now.return_value = fake_today
        mock_dt.strptime = datetime.strptime
        db._purge_old_events()
        db._conn.commit()

    remaining = set(_all_ts(db))
    all_ok = True

    for ts in should_delete:
        if ts in remaining:
            fail(f"Should have been deleted but survived: {ts}")
            all_ok = False
        else:
            ok(f"Correctly deleted:  {ts}")

    for ts in should_keep:
        if ts not in remaining:
            fail(f"Should have survived but was deleted: {ts}")
            all_ok = False
        else:
            ok(f"Correctly kept:     {ts}")

    return all_ok


# Тест 5 — високосный год (31 марта 2024 → 29 февраля 2024)


def test_leap_year_edge_case() -> None:
    section("TEST 5 · Leap year (31 Mar 2024 → clamp to 29 Feb 2024)")

    db = _make_db()
    fake_today = datetime(2024, 3, 31, 12, 0, 0)

    should_delete = ["2024-02-28 23:59:59", "2024-01-01 00:00:00"]
    should_keep = ["2024-02-29 00:00:00", "2024-03-15 00:00:00"]

    for ts in should_delete + should_keep:
        _insert_event(db, ts)

    with patch("core.database.datetime") as mock_dt:
        mock_dt.now.return_value = fake_today
        mock_dt.strptime = datetime.strptime
        db._purge_old_events()
        db._conn.commit()

    remaining = set(_all_ts(db))
    all_ok = True

    for ts in should_delete:
        if ts in remaining:
            fail(f"Should have been deleted but survived: {ts}")
            all_ok = False
        else:
            ok(f"Correctly deleted:  {ts}")

    for ts in should_keep:
        if ts not in remaining:
            fail(f"Should have survived but was deleted: {ts}")
            all_ok = False
        else:
            ok(f"Correctly kept:     {ts}")

    return all_ok


# Тест 6 — атомарность: БД остаётся целостной при ошибке очистки


def test_atomicity_on_error() -> None:
    section("TEST 6 · Atomicity — rollback keeps DB intact on error")

    db = _make_db()
    vid = db.add_vehicle("Б002ББ")
    _insert_event(db, "2020-01-01 00:00:00", name="Б002ББ")  # старое, подлежит очистке
    before = _count_events(db)

    # Заставляем _purge_old_events упасть, чтобы откатилась вся транзакция.
    original_purge = db._purge_old_events

    def broken_purge():
        raise sqlite3.OperationalError("simulated disk error")

    db._purge_old_events = broken_purge

    try:
        db.update_status_and_log("vehicle", vid, "Б002ББ", "arrived")
        fail("Expected DatabaseError was not raised")
        return False
    except Exception:
        pass

    after = _count_events(db)
    db._purge_old_events = original_purge  # восстановление

    if after == before:
        ok(f"Row count unchanged after failed transaction ({before} → {after})")
        return True
    else:
        fail(f"Row count changed despite rollback ({before} → {after})")
        return False


# Запуск


def main() -> None:
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║         Event purge smoke-tests (in-memory DB)          ║")
    print("╚══════════════════════════════════════════════════════════╝")

    results = [
        test_cutoff_arithmetic(),
        test_purge_boundary(),
        test_year_rollover_e2e(),
        test_short_month_edge_case(),
        test_leap_year_edge_case(),
        test_atomicity_on_error(),
    ]

    summarize(results)


if __name__ == "__main__":
    main()
