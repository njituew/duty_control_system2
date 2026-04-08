"""Manual smoke-test for the rolling-window event purge.

The script works on an ISOLATED in-memory SQLite database so your real
database.db is never touched.

What it checks
--------------
1.  Boundary correctness — only events older than exactly 1 calendar month
    are deleted; nothing else is removed.
2.  Year rollover — a purge triggered on 2027-01-15 correctly deletes events
    from 2026-12-14 and earlier, keeps 2026-12-15 and later.
3.  Month-length edge case — a purge on a 31st-day month (e.g. 2026-03-31)
    gracefully handles February (no Feb-31) and keeps events from 2026-02-28.
4.  End-to-end via Database.update_status_and_log — purge fires inside the
    real public method, not just the private helper.
"""

import sqlite3
import sys
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, ".")

from database import Database, _cutoff_ts  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_db() -> Database:
    """Return a Database backed by an in-memory SQLite — real DB never touched."""
    return Database(path=":memory:")


def _insert_event(
    db: Database, ts: str, event_type: str = "arrived", name: str = "Тест"
) -> None:
    """Bypass the public API and write a raw event row with an arbitrary ts."""
    db._conn.execute(
        "INSERT INTO events (entity_type, entity_id, entity_name, event_type, ts) "
        "VALUES ('vehicle', 1, ?, ?, ?)",
        (name, event_type, ts),
    )
    db._conn.commit()


def _count_events(db: Database) -> int:
    return db._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def _all_ts(db: Database) -> list[str]:
    rows = db._conn.execute("SELECT ts FROM events ORDER BY ts").fetchall()
    return [r[0] for r in rows]


def ok(label: str) -> None:
    print(f"  \033[32m✓\033[0m  {label}")


def fail(label: str, detail: str = "") -> None:
    print(f"  \033[31m✗\033[0m  {label}")
    if detail:
        print(f"       {detail}")


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — _cutoff_ts arithmetic
# ──────────────────────────────────────────────────────────────────────────────


def test_cutoff_arithmetic() -> None:
    section("TEST 1 · _cutoff_ts calendar arithmetic")

    cases = [
        # (fake_now,              expected_cutoff_date_prefix)
        ("2027-01-15 10:00:00", "2026-12-15"),  # year rollover
        ("2027-01-01 00:00:00", "2026-12-01"),  # 1 Jan → 1 Dec
        ("2026-03-31 23:59:59", "2026-02-28"),  # 31 Mar → clamp to Feb 28
        ("2026-03-15 08:30:00", "2026-02-15"),  # normal case
        ("2026-12-31 12:00:00", "2026-11-30"),  # 31 Dec → clamp Nov 30
        ("2024-03-31 00:00:00", "2024-02-29"),  # leap year 2024
        ("2026-02-28 00:00:00", "2026-01-28"),  # Feb → Jan
    ]

    all_ok = True
    for fake_now_str, expected_prefix in cases:
        fake_now = datetime.strptime(fake_now_str, "%Y-%m-%d %H:%M:%S")
        with patch("database.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime
            result = _cutoff_ts(1)

        passed = result.startswith(expected_prefix)
        label = f"now={fake_now_str}  →  cutoff starts with {expected_prefix}  (got {result[:10]})"
        if passed:
            ok(label)
        else:
            fail(label)
            all_ok = False

    return all_ok


# ──────────────────────────────────────────────────────────────────────────────
# Test 2 — boundary: only strictly-old rows are deleted
# ──────────────────────────────────────────────────────────────────────────────


def test_purge_boundary() -> None:
    section("TEST 2 · Purge boundary — keeps events on cutoff date, deletes older")

    db = _make_db()

    # Fake "today" = 2027-01-15 → cutoff = 2026-12-15 00:00:00
    fake_now = datetime(2027, 1, 15, 10, 0, 0)

    # Events that MUST be deleted (ts < 2026-12-15 00:00:00)
    should_delete = [
        "2026-12-14 23:59:59",  # one second before cutoff
        "2026-11-01 00:00:00",  # two months ago
        "2026-06-15 12:00:00",  # half a year ago
    ]
    # Events that MUST survive (ts >= 2026-12-15 00:00:00)
    should_keep = [
        "2026-12-15 00:00:00",  # exactly on the cutoff — must survive
        "2026-12-15 00:00:01",  # one second after cutoff
        "2027-01-10 08:00:00",  # recent
    ]

    for ts in should_delete + should_keep:
        _insert_event(db, ts)

    assert _count_events(db) == len(should_delete) + len(should_keep)

    with patch("database.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.strptime = datetime.strptime
        db._purge_old_events()
        db._conn.commit()

    remaining = set(_all_ts(db))
    all_ok = True

    for ts in should_delete:
        if ts in remaining:
            fail(f"Should have been deleted but survived: {ts}")
            all_ok = False
        else:
            ok(f"Correctly deleted:  {ts}")

    for ts in should_keep:
        if ts not in remaining:
            fail(f"Should have survived but was deleted: {ts}")
            all_ok = False
        else:
            ok(f"Correctly kept:     {ts}")

    return all_ok


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 — year rollover end-to-end (real public method)
# ──────────────────────────────────────────────────────────────────────────────


def test_year_rollover_e2e() -> None:
    section("TEST 3 · Year rollover via update_status_and_log (end-to-end)")

    db = _make_db()

    # Add a real vehicle so update_status_and_log has something to UPDATE.
    vid = db.add_vehicle("А001АА")

    # Seed old events directly — before the fake "today"
    fake_today = datetime(2027, 1, 15, 9, 0, 0)
    old_ts = "2026-12-14 10:00:00"  # should be purged (before 2026-12-15)
    keep_ts = "2026-12-15 00:00:00"  # should survive (on cutoff boundary)

    _insert_event(db, old_ts, name="А001АА")
    _insert_event(db, keep_ts, name="А001АА")

    before = _count_events(db)

    with patch("database.datetime") as mock_dt:
        mock_dt.now.return_value = fake_today
        mock_dt.strptime = datetime.strptime
        # Calling the real public method — triggers purge inside the transaction
        db.update_status_and_log("vehicle", vid, "А001АА", "arrived")

    after_ts = _all_ts(db)
    all_ok = True

    if old_ts in after_ts:
        fail(f"Old event was NOT deleted: {old_ts}")
        all_ok = False
    else:
        ok(f"Old event deleted correctly: {old_ts}")

    if keep_ts not in after_ts:
        fail(f"Boundary event was wrongly deleted: {keep_ts}")
        all_ok = False
    else:
        ok(f"Boundary event kept correctly: {keep_ts}")

    # The new event written by update_status_and_log must also be present
    new_events = [ts for ts in after_ts if ts.startswith("2027-01-15")]
    if new_events:
        ok(f"New event written correctly: {new_events[0]}")
    else:
        fail("New event from update_status_and_log is missing")
        all_ok = False

    return all_ok


# ──────────────────────────────────────────────────────────────────────────────
# Test 4 — month-length edge case (31 Mar → Feb 28)
# ──────────────────────────────────────────────────────────────────────────────


def test_short_month_edge_case() -> None:
    section("TEST 4 · Short-month edge case (31 Mar → clamp to 28 Feb)")

    db = _make_db()
    fake_today = datetime(2026, 3, 31, 12, 0, 0)

    # cutoff should be 2026-02-28 00:00:00  (Feb has no 31st)
    should_delete = [
        "2026-02-27 23:59:59",
        "2026-01-15 00:00:00",
    ]
    should_keep = [
        "2026-02-28 00:00:00",  # exactly on the (clamped) cutoff
        "2026-03-01 00:00:00",
        "2026-03-31 11:00:00",
    ]

    for ts in should_delete + should_keep:
        _insert_event(db, ts)

    with patch("database.datetime") as mock_dt:
        mock_dt.now.return_value = fake_today
        mock_dt.strptime = datetime.strptime
        db._purge_old_events()
        db._conn.commit()

    remaining = set(_all_ts(db))
    all_ok = True

    for ts in should_delete:
        if ts in remaining:
            fail(f"Should have been deleted but survived: {ts}")
            all_ok = False
        else:
            ok(f"Correctly deleted:  {ts}")

    for ts in should_keep:
        if ts not in remaining:
            fail(f"Should have survived but was deleted: {ts}")
            all_ok = False
        else:
            ok(f"Correctly kept:     {ts}")

    return all_ok


# ──────────────────────────────────────────────────────────────────────────────
# Test 5 — leap year (31 Mar 2024 → 29 Feb 2024)
# ──────────────────────────────────────────────────────────────────────────────


def test_leap_year_edge_case() -> None:
    section("TEST 5 · Leap year (31 Mar 2024 → clamp to 29 Feb 2024)")

    db = _make_db()
    fake_today = datetime(2024, 3, 31, 12, 0, 0)

    should_delete = ["2024-02-28 23:59:59", "2024-01-01 00:00:00"]
    should_keep = ["2024-02-29 00:00:00", "2024-03-15 00:00:00"]

    for ts in should_delete + should_keep:
        _insert_event(db, ts)

    with patch("database.datetime") as mock_dt:
        mock_dt.now.return_value = fake_today
        mock_dt.strptime = datetime.strptime
        db._purge_old_events()
        db._conn.commit()

    remaining = set(_all_ts(db))
    all_ok = True

    for ts in should_delete:
        if ts in remaining:
            fail(f"Should have been deleted but survived: {ts}")
            all_ok = False
        else:
            ok(f"Correctly deleted:  {ts}")

    for ts in should_keep:
        if ts not in remaining:
            fail(f"Should have survived but was deleted: {ts}")
            all_ok = False
        else:
            ok(f"Correctly kept:     {ts}")

    return all_ok


# ──────────────────────────────────────────────────────────────────────────────
# Test 6 — atomicity: DB stays consistent if purge raises
# ──────────────────────────────────────────────────────────────────────────────


def test_atomicity_on_error() -> None:
    section("TEST 6 · Atomicity — rollback keeps DB intact on error")

    db = _make_db()
    vid = db.add_vehicle("Б002ББ")
    _insert_event(db, "2020-01-01 00:00:00", name="Б002ББ")  # old, would be purged
    before = _count_events(db)

    # Force _purge_old_events to raise so the whole transaction rolls back
    original_purge = db._purge_old_events

    def broken_purge():
        raise sqlite3.OperationalError("simulated disk error")

    db._purge_old_events = broken_purge

    try:
        db.update_status_and_log("vehicle", vid, "Б002ББ", "arrived")
        fail("Expected DatabaseError was not raised")
        return False
    except Exception:
        pass

    after = _count_events(db)
    db._purge_old_events = original_purge  # restore

    if after == before:
        ok(f"Row count unchanged after failed transaction ({before} → {after})")
        return True
    else:
        fail(f"Row count changed despite rollback ({before} → {after})")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║         Event purge smoke-tests (in-memory DB)          ║")
    print("╚══════════════════════════════════════════════════════════╝")

    results = [
        test_cutoff_arithmetic(),
        test_purge_boundary(),
        test_year_rollover_e2e(),
        test_short_month_edge_case(),
        test_leap_year_edge_case(),
        test_atomicity_on_error(),
    ]

    passed = sum(1 for r in results if r)
    total = len(results)

    print(f"\n{'═' * 60}")
    if passed == total:
        print(f"  \033[32m✓ All {total} tests passed\033[0m")
    else:
        print(f"  \033[31m✗ {total - passed} of {total} tests FAILED\033[0m")
    print(f"{'═' * 60}\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
