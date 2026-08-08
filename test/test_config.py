"""Тесты конфигурации: набор статусов и цикл их переключения."""

import pytest

from core.config import STATUS_ALL, STATUS_ORDER, next_status


def test_status_set_is_closed() -> None:
    """Набор статусов — это всегда idle плюс цикл из конфига."""
    assert STATUS_ALL == frozenset({"idle", *STATUS_ORDER})
    assert "idle" not in STATUS_ORDER


@pytest.mark.parametrize(
    "current,expected",
    [
        ("idle", "arrived"),  # первый статус цикла
        ("arrived", "departed"),
        ("departed", "arrived"),
        ("unknown", "arrived"),  # любой внешний статус -> первый в цикле
        ("", "arrived"),
    ],
    ids=["idle", "arrived", "departed", "unknown", "empty"],
)
def test_next_status_cycles(current: str, expected: str) -> None:
    assert next_status(current) == expected