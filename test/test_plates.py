"""Тесты нормализации номера: core.plates.normalize_plate_number."""

import pytest

from core.plates import normalize_plate_number


@pytest.mark.parametrize(
    "raw",
    [
        "0010 PC-1",
        "0010PC-1",
        "0010 PC 1",
        "0010PC1",
        "PC 0010-1",
        "1-0010PC",
        "10010PC",  # регион спереди, буквы сзади (слитая запись)
        "PC00101",  # буквы спереди, регион сзади (слитая запись)
        "РС0-0010",  # серия с регионом 0
        "0010РС0",
        "0010-РС0",
    ],
    ids=[
        "with-dashes",
        "glued-dash",
        "spaces",
        "fully-glued",
        "letters-front",
        "dash-chez",
        "glued-region-front",
        "glued-region-back",
        "rs0-dash",
        "rs0-suffix",
        "rs0-glued",
    ],
)
def test_normalizes_to_0010(raw: str) -> None:
    assert normalize_plate_number(raw) == "0010"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1234 АВ 7", "1234"),
        ("АВ 1234-7", "1234"),
        ("РС 0001", "0001"),
        ("0010", "0010"),
        ("", None),
        ("ABC", None),
        (None, None),
    ],
    ids=[
        "standard",
        "letters-front",
        "rs-numeric",
        "digits-only",
        "empty",
        "no-digits",
        "none",
    ],
)
def test_plain_and_invalid(raw: str | None, expected: str | None) -> None:
    assert normalize_plate_number(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("PC12345PC", "12345"),  # буквы с обеих сторон — фолбэк на длиннейший прогон
        ("12345", "12345"),  # один слитый 5-значный прогон без букв
        ("123456", "123456"),  # 6 цифр — фолбэк на самый длинный прогон
        ("12 3456", "3456"),  # из двух прогонов выигрывает 4-значный
        ("   ", None),
    ],
    ids=[
        "letters-both-sides",
        "five-digits-no-letters",
        "six-digits",
        "two-groups",
        "whitespace",
    ],
)
def test_ambiguous_and_fallback(raw: str | None, expected: str | None) -> None:
    """Поведение неоднозначных и нестандартных прогонов цифр зафиксировано."""
    assert normalize_plate_number(raw) == expected
