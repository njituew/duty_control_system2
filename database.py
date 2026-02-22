"""Работа с базой данных SQLite."""

import sqlite3
from datetime import datetime

from config import DB_PATH


def _now() -> str:
    """Текущая метка времени в формате ISO."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: str = DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

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

        # Добавить колонку status в старые БД без неё
        for table in ("vehicles", "commanders"):
            try:
                self.conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN status TEXT NOT NULL DEFAULT 'idle'"
                )
                self.conn.commit()
            except sqlite3.OperationalError:
                pass  # колонка уже есть

    # ─────────────────────── Транспортные средства ────────────────────

    def add_vehicle(self, number: str) -> int | None:
        """Добавляет ТС. Возвращает id или None при дубликате."""
        try:
            cur = self.conn.execute(
                "INSERT INTO vehicles (number, created) VALUES (?, ?)",
                (number, _now()),
            )
            self.conn.commit()
            self._log("vehicle", cur.lastrowid, number, "created")
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def delete_vehicle(self, vid: int):
        row = self.conn.execute(
            "SELECT number FROM vehicles WHERE id = ?", (vid,)
        ).fetchone()
        if row:
            self._log("vehicle", vid, row["number"], "deleted")
        self.conn.execute("DELETE FROM vehicles WHERE id = ?", (vid,))
        self.conn.commit()

    def get_vehicles(self, search: str = "") -> list:
        return self.conn.execute(
            "SELECT * FROM vehicles WHERE number LIKE ? ORDER BY number",
            (f"%{search}%",),
        ).fetchall()

    # ───────────────────────────── Командиры ──────────────────────────

    def add_commander(self, name: str) -> int | None:
        """Добавляет командира. Возвращает id или None при дубликате."""
        try:
            cur = self.conn.execute(
                "INSERT INTO commanders (name, created) VALUES (?, ?)",
                (name, _now()),
            )
            self.conn.commit()
            self._log("commander", cur.lastrowid, name, "created")
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def delete_commander(self, cid: int):
        row = self.conn.execute(
            "SELECT name FROM commanders WHERE id = ?", (cid,)
        ).fetchone()
        if row:
            self._log("commander", cid, row["name"], "deleted")
        self.conn.execute("DELETE FROM commanders WHERE id = ?", (cid,))
        self.conn.commit()

    def get_commanders(self, search: str = "") -> list:
        return self.conn.execute(
            "SELECT * FROM commanders WHERE name LIKE ? ORDER BY name",
            (f"%{search}%",),
        ).fetchall()

    # ─────────────────────────────── Статусы ──────────────────────────

    def update_status_and_log(
        self, entity_type: str, entity_id: int, entity_name: str, status: str
    ):
        """Обновляет статус и записывает событие в одной транзакции."""
        table = "vehicles" if entity_type == "vehicle" else "commanders"
        self.conn.execute(
            f"UPDATE {table} SET status = ? WHERE id = ?", (status, entity_id)
        )
        self.conn.execute(
            "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity_id, entity_name, status, _now()),
        )
        self.conn.commit()

    # ─────────────────────────────── События ──────────────────────────

    def _log(self, entity_type: str, entity_id: int, entity_name: str, event_type: str):
        self.conn.execute(
            "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity_id, entity_name, event_type, _now()),
        )
        self.conn.commit()

    def get_events(self, search: str = "", limit: int = 300) -> list:
        q = f"%{search}%"
        return self.conn.execute(
            """
            SELECT * FROM events
            WHERE entity_name LIKE ? OR event_type LIKE ? OR entity_type LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (q, q, q, limit),
        ).fetchall()

    def clear_events(self):
        self.conn.execute("DELETE FROM events")
        self.conn.commit()

    # ───────────────────────────── Статистика ─────────────────────────

    def stats(self) -> dict:
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

    def recent_activity(self, limit: int = 5) -> list:
        return self.conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
