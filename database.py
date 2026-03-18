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
            self._ensure_updated_column()
        except sqlite3.Error as e:
            raise DatabaseError(f"Cannot open database '{path}': {e}") from e

    # ─────────────────────────── Schema ────────────────────────────

    def _migrate(self) -> None:
        """Create tables on first run if they do not already exist."""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vehicles (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                number  TEXT    NOT NULL UNIQUE,
                status  TEXT    NOT NULL DEFAULT 'idle',
                created TEXT    NOT NULL,
                updated TEXT
            );
            CREATE TABLE IF NOT EXISTS commanders (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT    NOT NULL UNIQUE,
                status  TEXT    NOT NULL DEFAULT 'idle',
                created TEXT    NOT NULL,
                updated TEXT
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

    # ─────────────────────────── Vehicles ──────────────────────────

    def add_vehicle(self, number: str) -> int:
        """Insert a new vehicle and return its generated id.

        Args:
            number: Registration number of the vehicle.

        Returns:
            The auto-assigned integer id of the new row.

        Raises:
            ValueError: If number is blank.
            DuplicateError: If a vehicle with this number already exists.
            DatabaseError: On any other SQLite error.
        """
        number = number.strip()
        if not number:
            raise ValueError("Vehicle number must not be empty.")
        try:
            cur = self.conn.execute(
                "INSERT INTO vehicles (number, status, created) VALUES (?, 'idle', ?)",
                (number, _now()),
            )
            self.conn.commit()
            self._log("vehicle", cur.lastrowid, number, "created")
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise DuplicateError(f"Vehicle '{number}' already exists.")
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to add vehicle: {e}") from e

    def delete_vehicle(self, vid: int) -> None:
        """Delete a vehicle by id and write a 'deleted' event.

        Args:
            vid: Primary key of the vehicle to delete.

        Raises:
            NotFoundError: If no vehicle with this id exists.
            DatabaseError: On any SQLite error.
        """
        try:
            row = self.conn.execute(
                "SELECT number FROM vehicles WHERE id = ?", (vid,)
            ).fetchone()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to delete vehicle: {e}") from e

        if not row:
            raise NotFoundError(f"Vehicle id={vid} not found.")

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
            raise DatabaseError(f"Failed to delete vehicle: {e}") from e

    def get_vehicles(self, search: str = "") -> list:
        """Return vehicles whose number contains the search substring.

        Args:
            search: Optional filter string (case-insensitive LIKE match).

        Returns:
            A list of sqlite3.Row objects ordered by number.

        Raises:
            DatabaseError: On any SQLite error.
        """
        try:
            return self.conn.execute(
                "SELECT * FROM vehicles WHERE number LIKE ? ORDER BY number",
                (f"%{search.strip()}%",),
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch vehicles: {e}") from e

    # ─────────────────────────── Commanders ────────────────────────

    def add_commander(self, name: str) -> int:
        """Insert a new commander and return his generated id.

        Args:
            name: Full name of the commander.

        Returns:
            The auto-assigned integer id of the new row.

        Raises:
            ValueError: If name is blank.
            DuplicateError: If a commander with this name already exists.
            DatabaseError: On any other SQLite error.
        """
        name = name.strip()
        if not name:
            raise ValueError("Commander name must not be empty.")
        try:
            cur = self.conn.execute(
                "INSERT INTO commanders (name, status, created) VALUES (?, 'idle', ?)",
                (name, _now()),
            )
            self.conn.commit()
            self._log("commander", cur.lastrowid, name, "created")
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise DuplicateError(f"Commander '{name}' already exists.")
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to add commander: {e}") from e

    def delete_commander(self, cid: int) -> None:
        """Delete a commander by id and write a 'deleted' event.

        Args:
            cid: Primary key of the commander to delete.

        Raises:
            NotFoundError: If no commander with this id exists.
            DatabaseError: On any SQLite error.
        """
        try:
            row = self.conn.execute(
                "SELECT name FROM commanders WHERE id = ?", (cid,)
            ).fetchone()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to delete commander: {e}") from e

        if not row:
            raise NotFoundError(f"Commander id={cid} not found.")

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
            raise DatabaseError(f"Failed to delete commander: {e}") from e

    def get_commanders(self, search: str = "") -> list:
        """Return commanders whose name contains the search substring.

        Args:
            search: Optional filter string (case-insensitive LIKE match).

        Returns:
            A list of sqlite3.Row objects ordered by name.

        Raises:
            DatabaseError: On any SQLite error.
        """
        try:
            return self.conn.execute(
                "SELECT * FROM commanders WHERE name LIKE ? ORDER BY name",
                (f"%{search.strip()}%",),
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch commanders: {e}") from e

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

    def _ensure_updated_column(self) -> None:
        """Add 'updated' column to vehicles/commanders if missing (migration)."""
        for table in ("vehicles", "commanders"):
            cols = [
                row[1]
                for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            ]
            if "updated" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN updated TEXT")
        self.conn.commit()

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
        self.conn.commit()

    def get_events(self, search: str = "", limit: int = 300) -> list:
        """Return events filtered by a search string, newest first.

        Args:
            search: Optional substring matched against entity name, event type,
                and entity type.
            limit: Maximum number of rows to return.

        Returns:
            A list of sqlite3.Row objects.

        Raises:
            DatabaseError: On any SQLite error.
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
