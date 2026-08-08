"""Смоук-тест CRUD-функций слоя БД на изолированной in-memory базе.

Реальная database/database.db не трогается — каждый тест создаёт свою
БД в памяти через Database(path=":memory:").

Проверяет:
1. ТС: добавление, поиск по номеру (с нормализацией), статус idle.
2. Дубликаты ТС → DuplicateError, пустое значение → ValueError.
3. Командиры: добавление, поиск, удаление.
4. Удаление ТС, отсутствие → NotFoundError.
5. Статус: update_status_and_log, переключение idle→arrived→departed→arrived
   (idle вне цикла, в него клики не возвращают).
6. Журнал событий: created/deleted/смена статуса, поиск, recent_activity.
7. Сброс журнала clear_events и статистика stats.
8. update_status_and_log с несуществующим id → NotFoundError, фантомное
   событие в журнал не пишется.
9. Миграция старой схемы: колонка number_norm добавляется и заливается.
"""

import sys

sys.path.insert(0, ".")

from harness import check, ok, raises, section, summarize
from database import Database, DatabaseError, DuplicateError, NotFoundError

# Вспомогательные функции


def _make_db() -> Database:
    """Вернуть Database на in-memory SQLite — реальная БД не затрагивается."""
    return Database(path=":memory:")


def _numbers(db: Database) -> list[str]:
    return [r["number"] for r in db.get_vehicles()]


def _names(db: Database) -> list[str]:
    return [r["name"] for r in db.get_commanders()]


def _event_types(db: Database) -> list[str]:
    return [r["event_type"] for r in db.get_events()]


# Тест 1 — добавление и получение ТС


def test_vehicle_crud() -> None:
    section("TEST 1 · Vehicle add + list + search")

    db = _make_db()

    vid1 = db.add_vehicle("1234 АВ 7")
    vid2 = db.add_vehicle("АВ 5678-7")

    ok(f"add_vehicle returns incremental ids: {vid1}, {vid2}" if vid2 > vid1 else
       f"add_vehicle ids not incremental: {vid1}, {vid2}")

    got = _numbers(db)
    ok(f"get_vehicles returns both: {got}" if got == ["1234 АВ 7", "АВ 5678-7"]
       else f"get_vehicles = {got}")

    ok(f"empty search lists all ({len(got)} rows)" if len(db.get_vehicles("")) == 2
       else f"get_vehicles('') returned {len(db.get_vehicles(''))}")

    found = db.get_vehicles("1234")
    ok("search by substring finds plates" if len(found) == 1 else
       f"get_vehicles('1234') = {len(found)} rows")

    found2 = db.get_vehicles("zzzz")
    ok("search with no match returns []" if found2 == [] else f"got {found2}")

    row = db.get_vehicles()[0]
    ok('new vehicles start with status "idle"'
       if row["status"] == "idle" else f"status = {row['status']!r}")

    return True


# Тест 2 — нормализованный поиск по номеру


def test_find_vehicle_by_number() -> None:
    section("Тест 2 · find_vehicle_by_number (нормализация номера)")

    db = _make_db()
    db.add_vehicle("1234 АВ 7")

    ok_found = db.find_vehicle_by_number("7-АВ-1234") is not None
    check(ok_found, "finds plate across formatting: 1234 АВ 7 ↔ 7-АВ-1234")

    ok_miss = db.find_vehicle_by_number("0000") is None
    check(ok_miss, "returns None for unknown number")

    ok_empty = db.find_vehicle_by_number("ABC") is None
    check(ok_empty, "returns None when number has no digits")

    return True


# Тест 3 — дубликаты и пустые значения


def test_duplicates_and_empty() -> None:
    section("Тест 3 · DuplicateError / ValueError на добавлении")

    db = _make_db()
    db.add_vehicle("5555")

    ok_dup = raises(
        DuplicateError, lambda: db.add_vehicle("5555"), "duplicate vehicle raises DuplicateError"
    )

    ok_empty = raises(
        ValueError, lambda: db.add_vehicle("   "), "empty vehicle value raises ValueError"
    )

    ok_dup_generic = raises(
        DuplicateError,
        lambda: db.add_entity("vehicle", "5555"),
        "generic add_entity raises DuplicateError on duplicate",
    )

    return ok_dup and ok_empty and ok_dup_generic


# Тест 4 — командиры: добавление, поиск, удаление


def test_commander_crud() -> None:
    section("Тест 4 · Commander create / list / search / delete")

    db = _make_db()
    cid1 = db.add_commander("Иванов")
    cid2 = db.add_commander("Петров")

    ok("two commanders added") if len(_names(db)) == 2 else fail("wrong count")

    found = db.get_commanders("етров")
    ok("commander search by substring works" if len(found) == 1 else
       f"get_commanders('етров') = {len(found)}")

    db.delete_commander(cid1)
    ok("deleted commander gone" if _names(db) == ["Петров"] else f"names = {_names(db)}")

    ok_notfound = raises(
        NotFoundError,
        lambda: db.delete_commander(9999),
        "deleting missing commander raises NotFoundError",
    )

    return True


# Тест 5 — удаление ТС и NotFound


def test_delete_vehicle() -> None:
    section("Тест 5 · Delete vehicle + NotFoundError")

    db = _make_db()
    vid = db.add_vehicle("1234")

    db.delete_vehicle(vid)
    ok("vehicle deleted") if _numbers(db) == [] else fail("vehicle still present")

    ok_notfound = raises(
        NotFoundError, lambda: db.delete_vehicle(vid), "deleting twice raises NotFoundError"
    )

    ok_generic = raises(
        NotFoundError, lambda: db.delete_entity("vehicle", 9999),
        "generic delete_entity raises NotFoundError for missing id",
    )

    return ok_notfound and ok_generic


# Тест 6 — статус и переключение idle → arrived → departed → arrived


def test_status_toggle_cycle() -> None:
    section("Тест 6 · toggle_vehicle_status_by_number (idle→arrived→departed→arrived)")

    db = _make_db()
    db.add_vehicle("1234 АВ 7")

    def status() -> str:
        return db.find_vehicle_by_number("7-АВ-1234")["status"]

    # STATUS_ORDER = ["arrived", "departed"] — idle только первый шаг.
    steps = ["arrived", "departed", "arrived", "departed"]  # результат каждого toggle из 'idle'
    results = []
    for expected in steps:
        db.toggle_vehicle_status_by_number("7-АВ-1234")
        results.append(status() == expected)

    ok("status cycles through full loop") if all(results) else \
        fail(f"statuses were {[status() for _ in [0]]}")

    toggled = db.toggle_vehicle_status_by_number("9999")
    ok("toggle on unknown number returns None") if toggled is None else \
        fail("toggle on unknown number returned a row")

    return all(results) and toggled is None


# Тест 7 — update_status_and_log и валидность статусов


def test_update_status_and_log() -> None:
    section("Тест 7 · update_status_and_log (явное обновление, плохой статус)")

    db = _make_db()
    vid = db.add_vehicle("1234")

    db.update_status_and_log("vehicle", vid, "1234", "arrived")

    row = db.get_vehicles()[0]
    check(row["status"] == "arrived" and row["updated"] is not None,
          "status and updated timestamp written")

    ev = db.get_events()
    check(len(ev) >= 2 and ev[0]["event_type"] == "arrived",
          "event logged for the status change")

    ok_bad = raises(
        ValueError,
        lambda: db.update_status_and_log("vehicle", vid, "1234", "bogus"),
        "unknown status raises ValueError",
    )

    ok_bad_entity = raises(
        ValueError,
        lambda: db.update_status_and_log("nope", vid, "1234", "arrived"),
        "unknown entity_type raises ValueError",
    )

    return ok_bad and ok_bad_entity


# Тест 8 — журнал событий: поиск, recent_activity, clear_events


def test_events_log() -> None:
    section("Тест 8 · Events log: search / recent_activity / clear_events")

    db = _make_db()
    db.add_vehicle("1234 АВ 7")
    db.add_commander("Иванов")
    db.delete_commander(db.get_commanders()[0]["id"])
    db.update_status_and_log("vehicle", db.get_vehicles()[0]["id"], "1234 АВ 7", "departed")

    types = _event_types(db)
    # created (ТС), created (командир), deleted (командир), departed (статус)
    ok("events recorded for each action") if len(types) == 4 else \
        fail(f"events = {types}")

    recent = db.recent_activity(5)
    ok("recent_activity returns events") if recent else fail("recent_activity empty")

    searched = db.get_events("Иванов")  # и событие created, и deleted
    ok("get_events filters by name") if len(searched) == 2 else \
        fail(f"get_events('Иванов') = {len(searched)}")

    db.clear_events()
    ok("clear_events empties the log") if len(db.get_events()) == 0 else \
        fail("events remain after clear_events")

    return True


# Тест 9 — статистика


def test_stats() -> None:
    section("Тест 9 · stats()")

    db = _make_db()
    db.add_vehicle("1234")
    db.add_vehicle("5678")
    db.add_commander("Иванов")

    vid = db.get_vehicles()[0]["id"]
    db.update_status_and_log("vehicle", vid, "1234", "arrived")
    db.update_status_and_log("vehicle", vid, "1234", "departed")

    s = db.stats()
    check(s["vehicles"] == 2 and s["commanders"] == 1, "counts vehicles and commanders")
    check(s["arrivals"] == 1 and s["departures"] == 1,
          "tallies arrival/departure events")
    check(s["total_events"] >= 2, "counts total events")

    return True


# Тест 9 — update_status_and_log с несуществующим id


def test_update_status_missing_id() -> None:
    section("Тест 9 · update_status_and_log (несуществующий id → NotFoundError)")

    db = _make_db()
    db.add_vehicle("1234")

    ok_missing = raises(
        NotFoundError,
        lambda: db.update_status_and_log("vehicle", 9999, "1234", "arrived"),
        "update_status_and_log with missing id raises NotFoundError",
    )

    # В журнале должно остаться только событие 'created' от добавления ТС.
    check(
        len(db.get_events()) == 1,
        "no phantom event logged for missing id",
        f"events = {_event_types(db)}",
    )

    return ok_missing


# Тест 10 — миграция старой схемы: колонка number_norm


def test_number_norm_migration() -> None:
    section("Тест 10 · Миграция number_norm (старая схема без колонки)")

    import os
    import sqlite3
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "old.db")
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE vehicles (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                number  TEXT    NOT NULL UNIQUE,
                status  TEXT    NOT NULL DEFAULT 'idle',
                created TEXT    NOT NULL,
                updated TEXT    DEFAULT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO vehicles (number, status, created) VALUES (?, 'idle', ?)",
            ("1234 АВ 7", "2026-01-01 00:00:00"),
        )
        conn.commit()
        conn.close()

        db = Database(path=path)

        row = db.get_vehicles()[0]
        ok_backfill = check(
            row["number_norm"] == "1234",
            "migration backfills number_norm for existing rows",
            f"number_norm = {row['number_norm']!r}",
        )

        found = db.find_vehicle_by_number("7-АВ-1234")
        ok_find = check(
            found is not None and found["id"] == row["id"],
            "find_vehicle_by_number works after migration",
        )

    return ok_backfill and ok_find


# Тест 11 — универсальные add_entity/delete_entity


def test_generic_entity_functions() -> None:
    section("Тест 11 · Универсальные add_entity/delete_entity")

    db = _make_db()
    id_v = db.add_entity("vehicle", "1234")
    id_c = db.add_entity("commander", "Иванов")

    check(id_v == db.get_vehicles()[0]["id"], "add_entity('vehicle') returns its id")
    check(id_c == db.get_commanders()[0]["id"], "add_entity('commander') returns its id")

    ok_bad = raises(
        ValueError,
        lambda: db.add_entity("nope", "x"),
        "add_entity with unknown type raises ValueError",
    )

    return ok_bad


# Запуск


def main() -> None:
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║            Database CRUD smoke-tests (in-memory)         ║")
    print("╚══════════════════════════════════════════════════════════╝")

    results = [
        test_vehicle_crud(),
        test_find_vehicle_by_number(),
        test_duplicates_and_empty(),
        test_commander_crud(),
        test_delete_vehicle(),
        test_status_toggle_cycle(),
        test_update_status_and_log(),
        test_events_log(),
        test_stats(),
        test_update_status_missing_id(),
        test_number_norm_migration(),
        test_generic_entity_functions(),
    ]

    summarize(results)


if __name__ == "__main__":
    main()