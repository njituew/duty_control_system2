"""Тесты чистой UI-логики без окна: форматирование меток времени."""

import pytest

from ui.components import fmt_timestamp


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-08-08 14:30:00", "14:30 08.08.2026"),
        ("2026-08-08 14:30:59", "14:30 08.08.2026"),
        ("not-a-date", "not-a-date"),
        ("", "—"),
        (None, "—"),
    ],
    ids=["valid", "seconds-ignored", "garbage", "empty", "none"],
)
def test_fmt_timestamp(raw: str | None, expected: str) -> None:
    assert fmt_timestamp(raw) == expected