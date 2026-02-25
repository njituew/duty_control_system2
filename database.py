"""Работа с базой данных SQLite."""

import logging
import sqlite3
from datetime import datetime

from config import DB_PATH

logger = logging.getLogger(__name__)


# ──────────────────────────── Исключения ────────────────────────────


class DatabaseError(Exception):
    """Базовая ошибка слоя БД."""


class DuplicateError(DatabaseError):
    """Запись с таким именем/номером уже существует."""


class NotFoundError(DatabaseError):
    """Запись не найдена."""


# ──────────────────────────── Утилиты ───────────────────────────────


def _now() -> str:
    """Текущая метка времени в формате ISO."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ──────────────────────────── Класс БД ──────────────────────────────


class Database:
    def __init__(self, path: str = DB_PATH):
        try:
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()
        except sqlite3.Error as e:
            raise DatabaseError(f"Не удалось открыть базу данных «{path}»: {e}") from e

    # ──────────────────────────── Миграции ────────────────────────────

    def _migrate(self):
        """Создаёт таблицы при первом запуске."""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vehicles (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                number  TEXT    NOT NULL UNIQUE,
                status  TEXT    NOT NULL DEFAULT 'idle',
                created TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS commanders (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT    NOT NULL UNIQUE,
                status  TEXT    NOT NULL DEFAULT 'idle',
                created TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT    NOT NULL,
                entity_id   INTEGER NOT NULL,
                entity_name TEXT    NOT NULL,
                event_type  TEXT    NOT NULL,
                ts          TEXT    NOT NULL
            );
            """
        )
        self.conn.commit()

    # ─────────────────────── Транспортные средства ────────────────────

    def add_vehicle(self, number: str) -> int:
        """Добавляет ТС. Возвращает id.

        Raises:
            ValueError: если number пустой.
            DuplicateError: если ТС с таким номером уже существует.
            DatabaseError: при ошибке БД.
        """
        number = number.strip()
        if not number:
            raise ValueError("Номер ТС не может быть пустым.")
        try:
            cur = self.conn.execute(
                "INSERT INTO vehicles (number, status, created) VALUES (?, 'idle', ?)",
                (number, _now()),
            )
            self.conn.commit()
            self._log("vehicle", cur.lastrowid, number, "created")
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise DuplicateError(f"ТС «{number}» уже существует.")
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при добавлении ТС: {e}") from e

    def delete_vehicle(self, vid: int) -> None:
        """Удаляет ТС по id.

        Raises:
            NotFoundError: если ТС не найдено.
            DatabaseError: при ошибке БД.
        """
        try:
            row = self.conn.execute(
                "SELECT number FROM vehicles WHERE id = ?", (vid,)
            ).fetchone()
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при удалении ТС: {e}") from e

        if not row:
            raise NotFoundError(f"ТС с id={vid} не найдено.")

        try:
            self.conn.execute(
                "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                ("vehicle", vid, row["number"], "deleted", _now()),
            )
            self.conn.execute("DELETE FROM vehicles WHERE id = ?", (vid,))
            self.conn.commit()
        except sqlite3.Error as e:
            self.conn.rollback()
            raise DatabaseError(f"Ошибка при удалении ТС: {e}") from e

    def get_vehicles(self, search: str = "") -> list:
        """Возвращает список ТС, отфильтрованный по подстроке номера.

        Raises:
            DatabaseError: при ошибке БД.
        """
        try:
            return self.conn.execute(
                "SELECT * FROM vehicles WHERE number LIKE ? ORDER BY number",
                (f"%{search.strip()}%",),
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при получении списка ТС: {e}") from e

    # ───────────────────────────── Командиры ──────────────────────────

    def add_commander(self, name: str) -> int:
        """Добавляет командира. Возвращает id.

        Raises:
            ValueError: если name пустой.
            DuplicateError: если командир с таким именем уже существует.
            DatabaseError: при ошибке БД.
        """
        name = name.strip()
        if not name:
            raise ValueError("ФИО командира не может быть пустым.")
        try:
            cur = self.conn.execute(
                "INSERT INTO commanders (name, status, created) VALUES (?, 'idle', ?)",
                (name, _now()),
            )
            self.conn.commit()
            self._log("commander", cur.lastrowid, name, "created")
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise DuplicateError(f"Командир «{name}» уже существует.")
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при добавлении командира: {e}") from e

    def delete_commander(self, cid: int) -> None:
        """Удаляет командира по id.

        Raises:
            NotFoundError: если командир не найден.
            DatabaseError: при ошибке БД.
        """
        try:
            row = self.conn.execute(
                "SELECT name FROM commanders WHERE id = ?", (cid,)
            ).fetchone()
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при удалении командира: {e}") from e

        if not row:
            raise NotFoundError(f"Командир с id={cid} не найден.")

        try:
            self.conn.execute(
                "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                ("commander", cid, row["name"], "deleted", _now()),
            )
            self.conn.execute("DELETE FROM commanders WHERE id = ?", (cid,))
            self.conn.commit()
        except sqlite3.Error as e:
            self.conn.rollback()
            raise DatabaseError(f"Ошибка при удалении командира: {e}") from e

    def get_commanders(self, search: str = "") -> list:
        """Возвращает список командиров, отфильтрованный по подстроке ФИО.

        Raises:
            DatabaseError: при ошибке БД.
        """
        try:
            return self.conn.execute(
                "SELECT * FROM commanders WHERE name LIKE ? ORDER BY name",
                (f"%{search.strip()}%",),
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при получении списка командиров: {e}") from e

    # ─────────────────────────────── Статусы ──────────────────────────

    def update_status_and_log(
        self, entity_type: str, entity_id: int, entity_name: str, status: str
    ) -> None:
        """Обновляет статус и записывает событие в одной транзакции.

        Raises:
            ValueError: если entity_type или status некорректны.
            DatabaseError: при ошибке БД.
        """
        valid_types = {"vehicle", "commander"}
        valid_statuses = {"idle", "arrived", "departed"}
        if entity_type not in valid_types:
            raise ValueError(f"Неизвестный тип сущности: {entity_type!r}")
        if status not in valid_statuses:
            raise ValueError(f"Неизвестный статус: {status!r}")

        table = "vehicles" if entity_type == "vehicle" else "commanders"
        try:
            self.conn.execute(
                f"UPDATE {table} SET status = ? WHERE id = ?", (status, entity_id)
            )
            self.conn.execute(
                "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (entity_type, entity_id, entity_name, status, _now()),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            self.conn.rollback()
            raise DatabaseError(f"Ошибка при обновлении статуса: {e}") from e

    # ─────────────────────────────── События ──────────────────────────

    def _log(self, entity_type: str, entity_id: int, entity_name: str, event_type: str) -> None:
        """Записывает событие в таблицу events."""
        self.conn.execute(
            "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity_id, entity_name, event_type, _now()),
        )
        self.conn.commit()

    def get_events(self, search: str = "", limit: int = 300) -> list:
        """Возвращает события, отфильтрованные по подстроке, в порядке убывания.

        Raises:
            DatabaseError: при ошибке БД.
        """
        try:
            q = f"%{search.strip()}%"
            return self.conn.execute(
                """
                SELECT * FROM events
                WHERE entity_name LIKE ? OR event_type LIKE ? OR entity_type LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (q, q, q, limit),
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при получении событий: {e}") from e

    def clear_events(self) -> None:
        """Удаляет всю историю событий.

        Raises:
            DatabaseError: при ошибке БД.
        """
        try:
            self.conn.execute("DELETE FROM events")
            self.conn.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при очистке истории: {e}") from e

    # ───────────────────────────── Статистика ─────────────────────────

    def stats(self) -> dict:
        """Возвращает сводную статистику по базе.

        Raises:
            DatabaseError: при ошибке БД.
        """
        try:
            def scalar(sql: str) -> int:
                return self.conn.execute(sql).fetchone()[0]

            return {
                "vehicles": scalar("SELECT COUNT(*) FROM vehicles"),
                "commanders": scalar("SELECT COUNT(*) FROM commanders"),
                "arrivals": scalar(
                    "SELECT COUNT(*) FROM events WHERE event_type='arrived'"
                ),
                "departures": scalar(
                    "SELECT COUNT(*) FROM events WHERE event_type='departed'"
                ),
                "total_events": scalar("SELECT COUNT(*) FROM events"),
            }
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при получении статистики: {e}") from e

    def recent_activity(self, limit: int = 5) -> list:
        """Возвращает последние события.

        Raises:
            DatabaseError: при ошибке БД.
        """
        try:
            return self.conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Ошибка при получении последних событий: {e}") from e
