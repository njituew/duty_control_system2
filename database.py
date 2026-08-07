"""Слой доступа к базе данных SQLite."""

import calendar
import logging
import sqlite3
from datetime import datetime, timezone

from config import DB_PATH, EVENT_RETENTION_MONTHS, STATUS_ORDER
from plates import normalize_plate_number

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Базовое исключение для ошибок слоя БД."""


class DuplicateError(DatabaseError):
    """Возникает, когда запись с таким именем или номером уже существует."""


class NotFoundError(DatabaseError):
    """Возникает, когда запрашиваемая запись не существует."""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _cutoff_ts(months: int) -> str:
    """Вернуть метку времени ровно months календарных месяцев назад.

    События с ts < cutoff считаются устаревшими и удаляются.
    """
    now = datetime.now(timezone.utc).astimezone()

    # Уменьшаем месяц, перенося год назад при переходе через январь.
    month = now.month - months
    year = now.year
    while month <= 0:
        month += 12
        year -= 1

    # Ограничиваем день последним числом целевого месяца.
    last_day_of_target = calendar.monthrange(year, month)[1]
    day = min(now.day, last_day_of_target)

    cutoff = now.replace(
        year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0
    )
    return cutoff.strftime("%Y-%m-%d %H:%M:%S")


# Белый список имён таблиц для динамического SQL — защита от инъекций в _migrate.
_ALLOWED_TABLES: frozenset[str] = frozenset({"vehicles", "commanders"})


class Database:
    """Тонкая обёртка над SQLite-соединением.

    Все записи проходят через транзакции и журнал событий в публичных
    методах. Вызывающий код не должен обращаться к _conn напрямую.
    """

    def __init__(self, path: str = DB_PATH):
        try:
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()
        except sqlite3.Error as e:
            raise DatabaseError(f"Cannot open database '{path}': {e}") from e

    def _migrate(self) -> None:
        """Создать таблицы при первом запуске и добавить недостающие колонки."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vehicles (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                number  TEXT    NOT NULL UNIQUE,
                status  TEXT    NOT NULL DEFAULT 'idle',
                created TEXT    NOT NULL,
                updated TEXT    DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS commanders (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT    NOT NULL UNIQUE,
                status  TEXT    NOT NULL DEFAULT 'idle',
                created TEXT    NOT NULL,
                updated TEXT    DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT    NOT NULL,
                entity_id   INTEGER NOT NULL,
                entity_name TEXT    NOT NULL,
                event_type  TEXT    NOT NULL,
                ts          TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);
            """
        )

        # Добавляем колонку 'updated' для БД, созданных до её введения.
        for table in ("vehicles", "commanders"):
            if table not in _ALLOWED_TABLES:
                raise ValueError(f"Unexpected table name in migration: {table!r}")
            cur = self._conn.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cur.fetchall()]
            if "updated" not in columns:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN updated TEXT DEFAULT NULL"
                )

        self._conn.commit()

    @staticmethod
    def _entity_table(entity_type: str) -> tuple[str, str]:
        """Вернуть (имя_таблицы, колонка_имени) для строки типа сущности."""
        if entity_type == "vehicle":
            return "vehicles", "number"
        if entity_type == "commander":
            return "commanders", "name"
        raise ValueError(f"Unknown entity type: {entity_type!r}")

    def _add_entity(self, entity_type: str, value: str) -> int:
        """Вставить новую сущность и вернуть её сгенерированный id."""
        table, col = self._entity_table(entity_type)
        value = value.strip()
        if not value:
            raise ValueError(f"{entity_type.capitalize()} value must not be empty.")
        try:
            cur = self._conn.execute(
                f"INSERT INTO {table} ({col}, status, created) VALUES (?, 'idle', ?)",
                (value, _now()),
            )
            self._log(entity_type, cur.lastrowid, value, "created")
            self._conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise DuplicateError(
                f"{entity_type.capitalize()} '{value}' already exists."
            )
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to add {entity_type}: {e}") from e

    def _delete_entity(self, entity_type: str, eid: int) -> None:
        """Удалить сущность по id и записать событие 'deleted'."""
        table, col = self._entity_table(entity_type)
        try:
            row = self._conn.execute(
                f"SELECT {col} FROM {table} WHERE id = ?", (eid,)
            ).fetchone()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to delete {entity_type}: {e}") from e
        if not row:
            raise NotFoundError(f"{entity_type.capitalize()} id={eid} not found.")
        try:
            self._log(entity_type, eid, row[0], "deleted")
            self._conn.execute(f"DELETE FROM {table} WHERE id = ?", (eid,))
            self._conn.commit()
        except sqlite3.Error as e:
            self._conn.rollback()
            raise DatabaseError(f"Failed to delete {entity_type}: {e}") from e

    def _get_entities(self, entity_type: str, search: str = "") -> list[sqlite3.Row]:
        """Вернуть сущности по подстроке поиска, отсортированные по имени."""
        table, col = self._entity_table(entity_type)
        try:
            return self._conn.execute(
                f"SELECT * FROM {table} WHERE {col} LIKE ? ORDER BY {col}",
                (f"%{search.strip()}%",),
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch {entity_type}s: {e}") from e

    def _log(
        self, entity_type: str, entity_id: int, entity_name: str, event_type: str
    ) -> None:
        """Записать событие без коммита — коммит выполняет вызывающий код."""
        self._conn.execute(
            "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity_id, entity_name, event_type, _now()),
        )

    def _purge_old_events(self) -> None:
        """Удалить события старше EVENT_RETENTION_MONTHS календарных месяцев.

        Выполняется без собственного коммита — вызывающий код коммитит
        окружающую транзакцию, поэтому очистка и новое событие атомарны.
        """
        cutoff = _cutoff_ts(EVENT_RETENTION_MONTHS)
        self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        logger.debug("Event purge: removed rows with ts < %s", cutoff)

    # ТС

    def add_vehicle(self, number: str) -> int:
        """Добавить ТС и вернуть его сгенерированный id."""
        return self._add_entity("vehicle", number)

    def delete_vehicle(self, vid: int) -> None:
        """Удалить ТС по id."""
        self._delete_entity("vehicle", vid)

    def get_vehicles(self, search: str = "") -> list[sqlite3.Row]:
        """Вернуть ТС, номер которых содержит подстроку поиска."""
        return self._get_entities("vehicle", search)

    def _normalize_number(self, number: str) -> str:
        """Извлечь основной 4-значный номер ТС для сопоставления."""
        return normalize_plate_number(number) or ""

    def find_vehicle_by_number(self, number: str) -> sqlite3.Row | None:
        """Вернуть ТС с совпадающим нормализованным номером."""
        normalized_target = self._normalize_number(number)
        if not normalized_target:
            return None
        try:
            rows = self._conn.execute("SELECT * FROM vehicles").fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to look up vehicle: {e}") from e

        for row in rows:
            if self._normalize_number(row["number"]) == normalized_target:
                return row
        return None

    def toggle_vehicle_status_by_number(self, number: str) -> sqlite3.Row | None:
        """Переключить статус ТС между arrived/departed по точному номеру.

        Повторяет цикл кликов по карточке: ТС вне STATUS_ORDER (т.е. 'idle')
        при первом совпадении переходит в первый статус цикла.

        Возвращает:
            Обновлённую строку ТС или None, если ТС с таким номером нет.
        """
        vehicle = self.find_vehicle_by_number(number)
        if vehicle is None:
            return None

        current = vehicle["status"]
        if current in STATUS_ORDER:
            new_status = STATUS_ORDER[
                (STATUS_ORDER.index(current) + 1) % len(STATUS_ORDER)
            ]
        else:
            new_status = STATUS_ORDER[0]

        self.update_status_and_log(
            "vehicle", vehicle["id"], vehicle["number"], new_status
        )
        return self.find_vehicle_by_number(number)

    # Командиры

    def add_commander(self, name: str) -> int:
        """Добавить командира и вернуть его сгенерированный id."""
        return self._add_entity("commander", name)

    def delete_commander(self, cid: int) -> None:
        """Удалить командира по id."""
        self._delete_entity("commander", cid)

    def get_commanders(self, search: str = "") -> list[sqlite3.Row]:
        """Вернуть командиров, имя которых содержит подстроку поиска."""
        return self._get_entities("commander", search)

    # Общие — используются UI-компонентами, получающими entity_type строкой

    def add_entity(self, entity_type: str, value: str) -> int:
        """Добавить ТС или командира по строке типа и вернуть id."""
        return self._add_entity(entity_type, value)

    def delete_entity(self, entity_type: str, eid: int) -> None:
        """Удалить ТС или командира по строке типа и id."""
        self._delete_entity(entity_type, eid)

    def get_entities(self, entity_type: str, search: str = "") -> list[sqlite3.Row]:
        """Вернуть ТС или командиров по подстроке поиска."""
        return self._get_entities(entity_type, search)

    # Статус

    def update_status_and_log(
        self, entity_type: str, entity_id: int, entity_name: str, status: str
    ) -> None:
        """Обновить статус сущности и записать событие в одной транзакции.

        Обновление и событие используют одну метку времени, поэтому колонка
        'updated' и журнал событий синхронны. В той же транзакции лениво
        удаляются устаревшие события, так что очистка и запись атомарны.

        Raises:
            ValueError:    При неизвестных entity_type или status.
            DatabaseError: При любой ошибке SQLite.
        """
        table, _ = self._entity_table(entity_type)

        if status not in {"idle", "arrived", "departed"}:
            raise ValueError(f"Unknown status: {status!r}")

        ts = _now()
        try:
            self._conn.execute(
                f"UPDATE {table} SET status = ?, updated = ? WHERE id = ?",
                (status, ts, entity_id),
            )
            self._conn.execute(
                "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (entity_type, entity_id, entity_name, status, ts),
            )
            self._purge_old_events()
            self._conn.commit()
        except sqlite3.Error as e:
            self._conn.rollback()
            raise DatabaseError(f"Failed to update status: {e}") from e

    # События

    def get_events(self, search: str = "", limit: int = 300) -> list[sqlite3.Row]:
        """Вернуть события по подстроке поиска, новые сверху."""
        try:
            q = f"%{search.strip()}%"
            return self._conn.execute(
                """
                SELECT * FROM events
                WHERE entity_name LIKE :q OR event_type LIKE :q OR entity_type LIKE :q
                ORDER BY id DESC
                LIMIT :lim
                """,
                {"q": q, "lim": limit},
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch events: {e}") from e

    def clear_events(self) -> None:
        """Удалить всю историю событий."""
        try:
            self._conn.execute("DELETE FROM events")
            self._conn.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to clear events: {e}") from e

    def recent_activity(self, limit: int = 5) -> list[sqlite3.Row]:
        """Вернуть последние события, новые сверху."""
        try:
            return self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch recent activity: {e}") from e

    # Статистика

    def stats(self) -> dict:
        """Вернуть агрегированные счётчики: vehicles, commanders, arrivals,
        departures, total_events.
        """
        try:
            row = self._conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM vehicles)                              AS vehicles,
                    (SELECT COUNT(*) FROM commanders)                            AS commanders,
                    (SELECT COUNT(*) FROM events WHERE event_type = 'arrived')  AS arrivals,
                    (SELECT COUNT(*) FROM events WHERE event_type = 'departed') AS departures,
                    (SELECT COUNT(*) FROM events)                                AS total_events
                """
            ).fetchone()
            return dict(row)
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch statistics: {e}") from e
