"""SQLite database access layer."""

import calendar
import logging
import sqlite3
from datetime import datetime

from config import DB_PATH, EVENT_RETENTION_MONTHS

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base exception for all database-layer errors."""


class DuplicateError(DatabaseError):
    """Raised when a record with the same name or number already exists."""


class NotFoundError(DatabaseError):
    """Raised when a requested record does not exist."""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cutoff_ts(months: int) -> str:
    """Return the ISO-8601 timestamp exactly months calendar months ago.

    Uses calendar arithmetic instead of timedelta(days=N) to handle
    year rollovers and months with different day counts correctly.

    Events with ts < cutoff are considered expired and will be deleted.
    """
    now = datetime.now()

    # Roll back the month counter, adjusting the year when we cross January.
    month = now.month - months
    year = now.year
    while month <= 0:
        month += 12
        year -= 1

    # Clamp the day to the last valid day of the target month.
    # Example: today is March 31, target is February → clamp to Feb 28/29.
    last_day_of_target = calendar.monthrange(year, month)[1]
    day = min(now.day, last_day_of_target)

    cutoff = now.replace(
        year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0
    )
    return cutoff.strftime("%Y-%m-%d %H:%M:%S")


# Whitelist for table names used in dynamic SQL — prevents injection in _migrate.
_ALLOWED_TABLES: frozenset[str] = frozenset({"vehicles", "commanders"})


class Database:
    """Thin wrapper around a SQLite connection.

    All writes go through transaction and event-logging machinery in the public
    methods. Callers must not access _conn directly.
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

        # Backfill 'updated' column for databases created before it was added.
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
        """Return (table_name, name_column) for the given entity type string."""
        if entity_type == "vehicle":
            return "vehicles", "number"
        if entity_type == "commander":
            return "commanders", "name"
        raise ValueError(f"Unknown entity type: {entity_type!r}")

    def _add_entity(self, entity_type: str, value: str) -> int:
        """Insert a new entity row and return its generated id."""
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
        """Delete an entity by id and write a 'deleted' event."""
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
        """Return entities filtered by a search substring, ordered by name."""
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
        """Append an event row without committing — caller is responsible for commit."""
        self._conn.execute(
            "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity_id, entity_name, event_type, _now()),
        )

    def _purge_old_events(self) -> None:
        """Delete events older than EVENT_RETENTION_MONTHS calendar months.

        Uses calendar arithmetic (see _cutoff_ts) so year rollovers and
        months with different day counts are handled correctly.
        Runs without its own commit — the caller commits the surrounding
        transaction, so the purge and the new event are atomic.
        """
        cutoff = _cutoff_ts(EVENT_RETENTION_MONTHS)
        self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        logger.debug("Event purge: removed rows with ts < %s", cutoff)

    # Vehicles

    def add_vehicle(self, number: str) -> int:
        """Insert a new vehicle and return its generated id."""
        return self._add_entity("vehicle", number)

    def delete_vehicle(self, vid: int) -> None:
        """Delete a vehicle by id."""
        self._delete_entity("vehicle", vid)

    def get_vehicles(self, search: str = "") -> list[sqlite3.Row]:
        """Return vehicles whose number contains the search substring."""
        return self._get_entities("vehicle", search)

    # Commanders

    def add_commander(self, name: str) -> int:
        """Insert a new commander and return his generated id."""
        return self._add_entity("commander", name)

    def delete_commander(self, cid: int) -> None:
        """Delete a commander by id."""
        self._delete_entity("commander", cid)

    def get_commanders(self, search: str = "") -> list[sqlite3.Row]:
        """Return commanders whose name contains the search substring."""
        return self._get_entities("commander", search)

    # Generic — used by UI components that receive entity_type as a string

    def add_entity(self, entity_type: str, value: str) -> int:
        """Add a vehicle or commander by type string and return its id."""
        return self._add_entity(entity_type, value)

    def delete_entity(self, entity_type: str, eid: int) -> None:
        """Delete a vehicle or commander by type string and id."""
        self._delete_entity(entity_type, eid)

    def get_entities(self, entity_type: str, search: str = "") -> list[sqlite3.Row]:
        """Return vehicles or commanders filtered by search substring."""
        return self._get_entities(entity_type, search)

    # Status

    def update_status_and_log(
        self, entity_type: str, entity_id: int, entity_name: str, status: str
    ) -> None:
        """Update entity status and write the event in a single transaction.

        Both the UPDATE and the event INSERT share one timestamp so the
        'updated' column and the event log stay in sync.

        Also lazily purges event rows older than EVENT_RETENTION_MONTHS within
        the same transaction, so the purge and the new write are always atomic.

        Raises:
            ValueError:    For unknown entity_type or status values.
            DatabaseError: On any SQLite error.
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

    # Events

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
        """Delete all event history."""
        try:
            self._conn.execute("DELETE FROM events")
            self._conn.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to clear events: {e}") from e

    def recent_activity(self, limit: int = 5) -> list[sqlite3.Row]:
        """Return the most recent events, newest first."""
        try:
            return self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to fetch recent activity: {e}") from e

    # Statistics

    def stats(self) -> dict:
        """Return aggregate counts as a dict with keys: vehicles, commanders,
        arrivals, departures, total_events.
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
