"""SQLite database access layer."""

import logging
import sqlite3
from datetime import datetime

from config import DB_PATH

logger = logging.getLogger(__name__)


# ─────────────────────────── Exceptions ────────────────────────────


class DatabaseError(Exception):
    """Base exception for all database-layer errors."""


class DuplicateError(DatabaseError):
    """Raised when a record with the same name or number already exists."""


class NotFoundError(DatabaseError):
    """Raised when a requested record does not exist."""


# ─────────────────────────── Helpers ───────────────────────────────


def _now() -> str:
    """Return the current timestamp as an ISO-formatted string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────── Database ──────────────────────────────


class Database:
    """Thin wrapper around a SQLite connection for this application."""

    def __init__(self, path: str = DB_PATH):
        try:
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()
        except sqlite3.Error as e:
            raise DatabaseError(f"Cannot open database '{path}': {e}") from e

    # ─────────────────────────── Schema ────────────────────────────

    def _migrate(self) -> None:
        """Create tables on first run if they do not already exist. Add missing columns."""
        # Create tables
        self.conn.executescript(
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
            """
        )

        # Migrate: add 'updated' column if missing
        for table, col in [("vehicles", "number"), ("commanders", "name")]:
            cur = self.conn.execute("PRAGMA table_info({})".format(table))
            columns = [row[1] for row in cur.fetchall()]
            if "updated" not in columns:
                self.conn.execute(
                    "ALTER TABLE {} ADD COLUMN updated TEXT DEFAULT NULL".format(table)
                )

        self.conn.commit()

    # ─────────────────────────── Vehicles ──────────────────────────

    # ─────────────────────────── Generic entity helpers ───────────

    @staticmethod
    def _entity_table(entity_type: str) -> tuple[str, str]:
        """Return (table_name, name_column) for an entity type."""
        if entity_type == "vehicle":
            return "vehicles", "number"
        if entity_type == "commander":
            return "commanders", "name"
        raise ValueError(f"Unknown entity type: {entity_type!r}")

    def _add_entity(self, entity_type: str, value: str) -> int:
        """Insert a new entity row and return its id."""
        table, col = self._entity_table(entity_type)
        value = value.strip()
        if not value:
            raise ValueError(f"{entity_type.capitalize()} value must not be empty.")
        try:
            cur = self.conn.execute(
                f"INSERT INTO {table} ({col}, status, created) VALUES (?, 'idle', ?)",
                (value, _now()),
            )
            self._log(entity_type, cur.lastrowid, value, "created")
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise DuplicateError(
                f"{entity_type.capitalize()} '{value}' already exists."
            )
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to add {entity_type}: {e}") from e

    def _delete_entity(self, entity_type: str, eid: int) -> None:
        """Delete an entity by id and log a 'deleted' event."""
        table, col = self._entity_table(entity_type)
        try:
            row = self.conn.execute(
                f"SELECT {col} FROM {table} WHERE id = ?", (eid,)
            ).fetchone()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to delete {entity_type}: {e}") from e
        if not row:
            raise NotFoundError(f"{entity_type.capitalize()} id={eid} not found.")
        try:
            self._log(entity_type, eid, row[0], "deleted")
            self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (eid,))
            self.conn.commit()
        except sqlite3.Error as e:
            self.conn.rollback()
            raise DatabaseError(f"Failed to delete {entity_type}: {e}") from e

    def _get_entities(self, entity_type: str, search: str = "") -> list:
        """Return entities filtered by search, ordered by the name column."""
        table, col = self._entity_table(entity_type)
        try:
            return self.conn.execute(
                f"SELECT * FROM {table} WHERE {col} LIKE ? ORDER BY {col}",
                (f"%{search.strip()}%",),
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch {entity_type}s: {e}") from e

    # ─────────────────────────── Vehicles ──────────────────────────

    def add_vehicle(self, number: str) -> int:
        """Insert a new vehicle and return its generated id."""
        return self._add_entity("vehicle", number)

    def delete_vehicle(self, vid: int) -> None:
        """Delete a vehicle by id and write a 'deleted' event."""
        self._delete_entity("vehicle", vid)

    def get_vehicles(self, search: str = "") -> list:
        """Return vehicles whose number contains the search substring."""
        return self._get_entities("vehicle", search)

    # ─────────────────────────── Commanders ────────────────────────

    def add_commander(self, name: str) -> int:
        """Insert a new commander and return his generated id."""
        return self._add_entity("commander", name)

    def delete_commander(self, cid: int) -> None:
        """Delete a commander by id and write a 'deleted' event."""
        self._delete_entity("commander", cid)

    def get_commanders(self, search: str = "") -> list:
        """Return commanders whose name contains the search substring."""
        return self._get_entities("commander", search)

    # ─────────────────────────── Statuses ──────────────────────────

    def update_status_and_log(
        self, entity_type: str, entity_id: int, entity_name: str, status: str
    ) -> None:
        """Update an entity's status and append the event in one transaction.

        Args:
            entity_type: Either 'vehicle' or 'commander'.
            entity_id: Primary key of the entity.
            entity_name: Display name used in the event log.
            status: New status — one of 'idle', 'arrived', 'departed'.

        Raises:
            ValueError: If entity_type or status is not a recognized value.
            DatabaseError: On any SQLite error.
        """
        valid_types = {"vehicle", "commander"}
        valid_statuses = {"idle", "arrived", "departed"}
        if entity_type not in valid_types:
            raise ValueError(f"Unknown entity type: {entity_type!r}")
        if status not in valid_statuses:
            raise ValueError(f"Unknown status: {status!r}")

        table = "vehicles" if entity_type == "vehicle" else "commanders"
        try:
            self.conn.execute(
                f"UPDATE {table} SET status = ?, updated = ? WHERE id = ?",
                (status, _now(), entity_id),
            )
            self.conn.execute(
                "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (entity_type, entity_id, entity_name, status, _now()),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            self.conn.rollback()
            raise DatabaseError(f"Failed to update status: {e}") from e

    # ─────────────────────────── Events ────────────────────────────

    def _log(
        self, entity_type: str, entity_id: int, entity_name: str, event_type: str
    ) -> None:
        # Internal helper — writes a single event row without committing.
        # Callers are responsible for calling conn.commit() afterwards.
        self.conn.execute(
            "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity_id, entity_name, event_type, _now()),
        )

    def get_events(self, search: str = "", limit: int = 300) -> list:
        """Return events filtered by a search string, newest first."""
        try:
            q = f"%{search.strip()}%"
            return self.conn.execute(
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
        """Delete all event history.

        Raises:
            DatabaseError: On any SQLite error.
        """
        try:
            self.conn.execute("DELETE FROM events")
            self.conn.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to clear events: {e}") from e

    # ─────────────────────────── Statistics ────────────────────────

    def stats(self) -> dict:
        """Return aggregate counts for the dashboard.

        Returns:
            A dict with keys: vehicles, commanders, arrivals, departures,
            total_events.

        Raises:
            DatabaseError: On any SQLite error.
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
            raise DatabaseError(f"Failed to fetch statistics: {e}") from e

    def recent_activity(self, limit: int = 5) -> list:
        """Return the most recent events.

        Args:
            limit: Maximum number of events to return.

        Returns:
            A list of sqlite3.Row objects, newest first.

        Raises:
            DatabaseError: On any SQLite error.
        """
        try:
            return self.conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch recent activity: {e}") from e
