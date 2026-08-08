"""CRUD-тесты слоя БД на изолированной in-memory базе.

Реальная database/database.db не трогается — каждая тестовая функция
получает свою БД в памяти через фикстуру `db` (Database(path=":memory:")).

Проверяет:
1. ТС: добавление, поиск (с нормализацией), статус idle.
2. Дубликаты ТС → DuplicateError, пустое значение → ValueError.
3. Командиры: добавление, поиск, удаление.
4. Удаление ТС, отсутствие → NotFoundError.
5. Статус: toggle_vehicle_status_by_number, цикл
   idle→arrived→departed→arrived (idle вне цикла, в него клики не возвращают).
6. Журнал событий: created/deleted/смена статуса, поиск, recent_activity.
7. Сброс журнала clear_events и статистика stats.
8. update_status_and_log с несуществующим id → NotFoundError, фантомное
   событие в журнал не пишется.
9. Миграция старой схемы: колонка number_norm добавляется и заливается.
10. Универсальные add_entity/delete_entity.
"""

import sqlite3

import pytest

from core.database import Database, DuplicateError, NotFoundError

# Вспомогательные функции


def _numbers(db: Database) -> list[str]:
    return [r["number"] for r in db.get_vehicles()]


def _names(db: Database) -> list[str]:
    return [r["name"] for r in db.get_commanders()]


def _event_types(db: Database) -> list[str]:
    return [r["event_type"] for r in db.get_events()]


# ТС: добавление, список, поиск


def test_vehicle_crud(db: Database) -> None:
    vid1 = db.add_vehicle("1234 АВ 7")
    vid2 = db.add_vehicle("АВ 5678-7")

    assert vid2 > vid1, "add_vehicle должен возвращать возрастающие id"
    assert _numbers(db) == ["1234 АВ 7", "АВ 5678-7"]

    assert len(db.get_vehicles("")) == 2
    assert len(db.get_vehicles("1234")) == 1
    assert db.get_vehicles("zzzz") == []

    assert db.get_vehicles()[0]["status"] == "idle"


def test_find_vehicle_by_number_normalizes(db: Database) -> None:
    db.add_vehicle("1234 АВ 7")

    assert db.find_vehicle_by_number("7-АВ-1234") is not None
    assert db.find_vehicle_by_number("0000") is None
    assert db.find_vehicle_by_number("ABC") is None


# Дубликаты и пустые значения


def test_add_duplicate_vehicle_raises(db: Database) -> None:
    db.add_vehicle("5555")

    with pytest.raises(DuplicateError):
        db.add_vehicle("5555")


def test_add_empty_vehicle_raises(db: Database) -> None:
    with pytest.raises(ValueError):
        db.add_vehicle("   ")


def test_add_entity_duplicate_raises(db: Database) -> None:
    db.add_entity("vehicle", "5555")

    with pytest.raises(DuplicateError):
        db.add_entity("vehicle", "5555")


# Командиры


def test_commander_crud(db: Database) -> None:
    cid1 = db.add_commander("Иванов")
    cid2 = db.add_commander("Петров")

    assert cid2 > cid1
    assert len(_names(db)) == 2
    assert len(db.get_commanders("етров")) == 1

    db.delete_commander(cid1)
    assert _names(db) == ["Петров"]

    with pytest.raises(NotFoundError):
        db.delete_commander(9999)


# Удаление ТС и NotFound


def test_delete_vehicle(db: Database) -> None:
    vid = db.add_vehicle("1234")

    db.delete_vehicle(vid)
    assert _numbers(db) == []

    with pytest.raises(NotFoundError):
        db.delete_vehicle(vid)

    with pytest.raises(NotFoundError):
        db.delete_entity("vehicle", 9999)


# Статус и переключение idle → arrived → departed → arrived


def test_toggle_cycles_status(db: Database) -> None:
    db.add_vehicle("1234 АВ 7")

    # STATUS_ORDER = ["arrived", "departed"] — idle только первый шаг.
    steps = ["arrived", "departed", "arrived", "departed"]
    for expected in steps:
        db.toggle_vehicle_status_by_number("7-АВ-1234")
        assert db.find_vehicle_by_number("7-АВ-1234")["status"] == expected


def test_toggle_unknown_number_returns_none(db: Database) -> None:
    db.add_vehicle("1234 АВ 7")

    assert db.toggle_vehicle_status_by_number("9999") is None


# update_status_and_log и валидность статусов


def test_update_status_and_log(db: Database) -> None:
    vid = db.add_vehicle("1234")
    db.update_status_and_log("vehicle", vid, "1234", "arrived")

    row = db.get_vehicles()[0]
    assert row["status"] == "arrived"
    assert row["updated"] is not None

    ev = db.get_events()
    assert len(ev) >= 2
    assert ev[0]["event_type"] == "arrived"

    with pytest.raises(ValueError):
        db.update_status_and_log("vehicle", vid, "1234", "bogus")

    with pytest.raises(ValueError):
        db.update_status_and_log("nope", vid, "1234", "arrived")


# Журнал событий


def test_events_log(db: Database) -> None:
    db.add_vehicle("1234 АВ 7")
    db.add_commander("Иванов")
    db.delete_commander(db.get_commanders()[0]["id"])
    db.update_status_and_log(
        "vehicle", db.get_vehicles()[0]["id"], "1234 АВ 7", "departed"
    )

    # created (ТС), created (командир), deleted (командир), departed (статус)
    assert sorted(_event_types(db)) == ["created", "created", "deleted", "departed"]

    assert bool(db.recent_activity(5))
    assert len(db.get_events("Иванов")) == 2  # и событие created, и deleted

    db.clear_events()
    assert db.get_events() == []


def test_update_status_missing_id(db: Database) -> None:
    db.add_vehicle("1234")

    with pytest.raises(NotFoundError):
        db.update_status_and_log("vehicle", 9999, "1234", "arrived")

    # В журнале должно остаться только событие 'created' от добавления ТС.
    assert len(db.get_events()) == 1


# Статистика


def test_stats(db: Database) -> None:
    db.add_vehicle("1234")
    db.add_vehicle("5678")
    db.add_commander("Иванов")

    vid = db.get_vehicles()[0]["id"]
    db.update_status_and_log("vehicle", vid, "1234", "arrived")
    db.update_status_and_log("vehicle", vid, "1234", "departed")

    s = db.stats()
    assert s["vehicles"] == 2
    assert s["commanders"] == 1
    assert s["arrivals"] == 1
    assert s["departures"] == 1
    assert s["total_events"] >= 2


# Миграция старой схемы


def test_number_norm_migration(tmp_path) -> None:
    path = tmp_path / "old.db"
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

    db = Database(path=str(path))

    row = db.get_vehicles()[0]
    assert row["number_norm"] == "1234"

    found = db.find_vehicle_by_number("7-АВ-1234")
    assert found is not None
    assert found["id"] == row["id"]


# Универсальные add_entity/delete_entity


def test_generic_entity_functions(db: Database) -> None:
    id_v = db.add_entity("vehicle", "1234")
    id_c = db.add_entity("commander", "Иванов")

    assert id_v == db.get_vehicles()[0]["id"]
    assert id_c == db.get_commanders()[0]["id"]

    with pytest.raises(ValueError):
        db.add_entity("nope", "x")
