"""SQLite database access layer."""

import logging
import sqlite3
from datetime import datetime

from config import DB_PATH

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base exception for all database-layer errors."""


class DuplicateError(DatabaseError):
    """Raised when a record with the same name or number already exists."""


class NotFoundError(DatabaseError):
    """Raised when a requested record does not exist."""


def _now() -> str:
    """Return the current timestamp as an ISO-formatted string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# Tables allowed in dynamic SQL fragments — guards against injection in _migrate.
_ALLOWED_TABLES: frozenset[str] = frozenset({"vehicles", "commanders"})


class Database:
    """Thin wrapper around a SQLite connection for this application.

    All writes go through the transaction and event-logging machinery
    exposed by the public methods; callers must not access _conn directly.
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
        """Create tables on first run and add any missing columns."""
        # Create tables
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
            """
        )

        # Add 'updated' column to older databases that pre-date it.
        # Table names come from the internal whitelist — no user input reaches here.
        for table, col in [("vehicles", "number"), ("commanders", "name")]:
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
        """Return (table_name, name_column) for an entity type."""
        if entity_type == "vehicle":
            return "vehicles", "number"
        if entity_type == "commander":
            return "commanders", "name"
        raise ValueError(f"Unknown entity type: {entity_type!r}")

    def _add_entity(self, entity_type: str, value: str) -> int:
        """Insert a new entity and return its generated id."""
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
        """Delete an entity by id and log a 'deleted' event."""
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
        """Return entities filtered by search, ordered by the name column."""
        table, col = self._entity_table(entity_type)
        try:
            return self._conn.execute(
                f"SELECT * FROM {table} WHERE {col} LIKE ? ORDER BY {col}",
                (f"%{search.strip()}%",),
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch {entity_type}s: {e}") from e

    def add_vehicle(self, number: str) -> int:
        """Insert a new vehicle and return its generated id."""
        return self._add_entity("vehicle", number)

    def delete_vehicle(self, vid: int) -> None:
        """Delete a vehicle by id and write a 'deleted' event."""
        self._delete_entity("vehicle", vid)

    def get_vehicles(self, search: str = "") -> list[sqlite3.Row]:
        """Return vehicles whose number contains the search substring."""
        return self._get_entities("vehicle", search)

    def add_commander(self, name: str) -> int:
        """Insert a new commander and return his generated id."""
        return self._add_entity("commander", name)

    def delete_commander(self, cid: int) -> None:
        """Delete a commander by id and write a 'deleted' event."""
        self._delete_entity("commander", cid)

    def get_commanders(self, search: str = "") -> list[sqlite3.Row]:
        """Return commanders whose name contains the search substring."""
        return self._get_entities("commander", search)

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
        table, _ = self._entity_table(
            entity_type
        )  # raises ValueError for unknown types

        valid_statuses = {"idle", "arrived", "departed"}
        if status not in valid_statuses:
            raise ValueError(f"Unknown status: {status!r}")

        try:
            self._conn.execute(
                f"UPDATE {table} SET status = ?, updated = ? WHERE id = ?",
                (status, _now(), entity_id),
            )
            self._conn.execute(
                "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (entity_type, entity_id, entity_name, status, _now()),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            self._conn.rollback()
            raise DatabaseError(f"Failed to update status: {e}") from e

    def _log(
        self, entity_type: str, entity_id: int, entity_name: str, event_type: str
    ) -> None:
        # Write a single event row without committing; caller must commit.
        self._conn.execute(
            "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity_id, entity_name, event_type, _now()),
        )

    def get_events(self, search: str = "", limit: int = 300) -> list[sqlite3.Row]:
        """Return events filtered by a search string, newest first."""
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
        """Delete all event history.

        Raises:
            DatabaseError: On any SQLite error.
        """
        try:
            self._conn.execute("DELETE FROM events")
            self._conn.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to clear events: {e}") from e

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
                return self._conn.execute(sql).fetchone()[0]

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

    def recent_activity(self, limit: int = 5) -> list[sqlite3.Row]:
        """Return the most recent events.

        Args:
            limit: Maximum number of events to return.

        Returns:
            A list of sqlite3.Row objects, newest first.

        Raises:
            DatabaseError: On any SQLite error.
        """
        try:
            return self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch recent activity: {e}") from e
