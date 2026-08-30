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

from core.database import Database, DatabaseError, DuplicateError, NotFoundError

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


# set_vehicle_status_by_number


def test_set_vehicle_status_by_number_basic(db: Database) -> None:
    db.add_vehicle("1234")

    v = db.set_vehicle_status_by_number("1234", "arrived")
    assert v is not None
    assert v["status"] == "arrived"
    assert v["updated"] is not None


def test_set_vehicle_status_by_number_unknown_returns_none(db: Database) -> None:
    assert db.set_vehicle_status_by_number("9999", "arrived") is None


def test_set_vehicle_status_by_number_updates_timestamp_on_same_status(
    db: Database, frozen_now
) -> None:
    """Повторное прибытие обновляет таймстемп и пишет новое событие."""
    from datetime import datetime

    db.add_vehicle("1234")

    # Первое прибытие: t=10:00
    frozen_now(datetime(2026, 1, 1, 10, 0, 0))
    v1 = db.set_vehicle_status_by_number("1234", "arrived")
    ts1 = v1["updated"]

    # Повторное прибытие: t=11:00 — таймстемп должен обновиться
    frozen_now(datetime(2026, 1, 1, 11, 0, 0))
    v2 = db.set_vehicle_status_by_number("1234", "arrived")
    ts2 = v2["updated"]

    assert ts2 > ts1, (
        f"Таймстемп должен обновиться при повторном прибытии: {ts1} -> {ts2}"
    )

    # В журнале — два события «arrived» (created + arrived1 + arrived2 ≥ 3)
    arrivals = [
        e for e in db.get_events() if e["event_type"] == "arrived"
    ]
    assert len(arrivals) >= 2, (
        f"Должны быть ≥2 события arrived, получено: {len(arrivals)}"
    )


def test_set_vehicle_status_by_number_departed_then_arrived(
    db: Database, frozen_now
) -> None:
    """Полный цикл: прибыл → убыл → прибыл (таймстемп обновляется)."""
    from datetime import datetime

    db.add_vehicle("1234")

    frozen_now(datetime(2026, 1, 1, 10, 0, 0))
    db.set_vehicle_status_by_number("1234", "arrived")
    v_dep = db.set_vehicle_status_by_number("1234", "departed")
    assert v_dep["status"] == "departed"

    frozen_now(datetime(2026, 1, 1, 12, 0, 0))
    v_arr2 = db.set_vehicle_status_by_number("1234", "arrived")
    assert v_arr2["status"] == "arrived"
    assert v_arr2["updated"] is not None


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


def test_generic_entity_functions_reject_unknown_type(db: Database) -> None:
    with pytest.raises(ValueError):
        db.get_entities("nope")
    with pytest.raises(ValueError):
        db.delete_entity("nope", 1)


def test_duplicate_and_empty_commander(db: Database) -> None:
    db.add_commander("Иванов")

    with pytest.raises(DuplicateError):
        db.add_commander("Иванов")

    with pytest.raises(ValueError):
        db.add_commander("   ")


def test_add_vehicle_strips_whitespace(db: Database) -> None:
    db.add_vehicle("  1234 АВ 7  ")

    assert db.get_vehicles()[0]["number"] == "1234 АВ 7"


def test_get_events_limit_is_clamped(db: Database) -> None:
    for i in range(5):
        db.add_vehicle(f"ТС {i}")

    assert len(db.get_events(limit=3)) == 3
    assert db.get_events(limit=0) == []
    assert db.get_events(limit=-5) == []
    assert len(db.get_events(limit=10_000_000)) == 5


def test_events_search_by_type(db: Database) -> None:
    db.add_vehicle("1234")
    db.add_commander("Иванов")

    created = db.get_events("created")
    assert len(created) == 2
    assert all(ev["event_type"] == "created" for ev in created)


def test_database_init_error(tmp_path) -> None:
    """Путь, указывающий на каталог, -> DatabaseError."""
    with pytest.raises(DatabaseError):
        Database(path=str(tmp_path))


# LIKE-инъекция и экранирование спецсимволов


def test_search_percent_literal(db: Database) -> None:
    """Символ % в поиске ищет literal '%', а не wildcard."""
    db.add_vehicle("100%")
    db.add_vehicle("1005")

    result = db.get_vehicles("100%")
    numbers = [r["number"] for r in result]
    assert "100%" in numbers
    assert "1005" not in numbers


def test_search_underscore_literal(db: Database) -> None:
    """Символ _ в поиске ищет literal '_', а не wildcard."""
    db.add_vehicle("A_B")
    db.add_vehicle("AXB")

    result = db.get_vehicles("A_B")
    numbers = [r["number"] for r in result]
    assert "A_B" in numbers
    assert "AXB" not in numbers


def test_events_search_percent_literal(db: Database) -> None:
    """Символ % в поиске событий ищет literal '%'."""
    db.add_vehicle("100%")
    ev = db.get_events("100%")
    assert len(ev) == 1
    assert ev[0]["entity_name"] == "100%"


def test_search_backslash_escape(db: Database) -> None:
    """Обратный слэш экранирует спецсимволы LIKE."""
    db.add_vehicle("C:\\Users")
    # _escape_like converts \ to \\, then LIKE ESCAPE '\' interprets \\ as literal \
    result = db.get_vehicles("C:\\Users")
    assert len(result) == 1


# close() и context manager


def test_close_prevents_further_queries(db: Database) -> None:
    """После close() обращение к БД вызывает DatabaseError."""
    db.add_vehicle("1234")
    db.close()

    with pytest.raises(DatabaseError):
        db.get_vehicles()


def test_context_manager_closes_connection() -> None:
    """with Database(...) as db: ... закрывает соединение при выходе."""
    with Database(path=":memory:") as db:
        db.add_vehicle("1234")
        assert len(db.get_vehicles()) == 1

    with pytest.raises(DatabaseError):
        db.get_vehicles()


def test_close_idempotent(db: Database) -> None:
    """Повторный close() не вызывает ошибку."""
    db.close()
    db.close()


# _delete_entity — обработка ошибок SQLite


class _ErrorRaisingProxy:
    """Proxy around sqlite3.Connection that can raise errors on specific SQL patterns."""

    def __init__(self, conn, error_sql_fragment=None, error_class=sqlite3.OperationalError):
        self._conn = conn
        self._error_sql_fragment = error_sql_fragment
        self._error_class = error_class

    def execute(self, sql, *args, **kwargs):
        if self._error_sql_fragment and self._error_sql_fragment in sql:
            raise self._error_class("simulated error")
        return self._conn.execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        return self._conn.executemany(sql, *args, **kwargs)

    def executescript(self, sql):
        return self._conn.executescript(sql)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_delete_entity_handles_db_error(db: Database) -> None:
    """Ошибка SQLite при SELECT в _delete_entity оборачивается в DatabaseError."""
    vid = db.add_vehicle("1234")

    proxy = _ErrorRaisingProxy(db._conn, error_sql_fragment="SELECT number FROM vehicles")
    db._conn = proxy

    with pytest.raises(DatabaseError, match="Failed to delete"):
        db.delete_vehicle(vid)

    db._conn = proxy._conn


# update_status_and_log — IntegrityError


class _SelectiveErrorProxy:
    """Proxy that raises error on specific SQL while passing through others."""

    def __init__(self, conn, error_sql_fragment=None, error_class=sqlite3.IntegrityError,
                 skip_first_n=0):
        self._conn = conn
        self._error_sql_fragment = error_sql_fragment
        self._error_class = error_class
        self._call_count = 0
        self._skip_first_n = skip_first_n

    def execute(self, sql, *args, **kwargs):
        self._call_count += 1
        if (self._call_count > self._skip_first_n
                and self._error_sql_fragment
                and self._error_sql_fragment in sql):
            raise self._error_class("simulated constraint")
        return self._conn.execute(sql, *args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_update_status_and_log_integrity_error(db: Database) -> None:
    """IntegrityError при INSERT в events оборачивается в DatabaseError."""
    vid = db.add_vehicle("1234")

    proxy = _SelectiveErrorProxy(
        db._conn,
        error_sql_fragment="INSERT INTO events",
        error_class=sqlite3.IntegrityError,
        skip_first_n=1,  # skip UPDATE, fail on INSERT
    )
    db._conn = proxy

    with pytest.raises(DatabaseError, match="Integrity error"):
        db.update_status_and_log("vehicle", vid, "1234", "arrived")

    db._conn = proxy._conn
    # Статус не изменился из-за отката
    assert db.get_vehicles()[0]["status"] == "idle"


# Проверка что _delete_entity ловит NotFoundError корректно


def test_delete_entity_not_found_propagates(db: Database) -> None:
    """NotFoundError от _delete_entity всплывает без оборачивания."""
    with pytest.raises(NotFoundError):
        db.delete_vehicle(9999)
