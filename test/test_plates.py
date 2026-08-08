"""Смоук-тест извлечения номера из строки номерного знака."""

import sys

sys.path.insert(0, ".")

from harness import check, section, summarize
from core.plates import normalize_plate_number


def _check_norm(raw: str | None, expected: str | None) -> bool:
    """Проверить один случай: нормализация raw должна дать expected."""
    got = normalize_plate_number(raw)
    return check(got == expected, f"normalize({raw!r})  →  {got!r}")


def test_all_variants() -> None:
    section("TEST 1 · Все варианты записи номера «0010 PC-1»")

    cases = [
        "0010 PC-1",
        "0010PC-1",
        "0010 PC 1",
        "0010PC1",
        "PC 0010-1",
        "1-0010PC",
        "10010PC",
    ]

    all_ok = True
    for raw in cases:
        all_ok = _check_norm(raw, "0010") and all_ok

    return all_ok


# Тест 2 — слитая запись региона и номера с разных сторон


def test_glued_region() -> None:
    section("TEST 2 · Регион «приклеен» к номеру без разделителя")

    cases = [
        ("10010PC", "0010"),  # регион спереди, буквы сзади
        ("PC00101", "0010"),  # буквы спереди, регион сзади
    ]

    all_ok = True
    for raw, expected in cases:
        all_ok = _check_norm(raw, expected) and all_ok

    return all_ok


# Тест 3 — серия с регионом 0 (президентский/служебный формат)


def test_region_zero() -> None:
    section("TEST 3 · Серия РС с регионом 0")

    cases = [
        "РС0-0010",
        "0010РС0",
        "0010-РС0",
    ]

    all_ok = True
    for raw in cases:
        all_ok = _check_norm(raw, "0010") and all_ok

    return all_ok


# Тест 4 — обычный «1234 АВ 7» и крайние случаи


def test_plain_and_edge_cases() -> None:
    section("TEST 4 · Стандартный формат и крайние случаи")

    pairs = [
        ("1234 АВ 7", "1234"),
        ("АВ 1234-7", "1234"),
        ("РС 0001", "0001"),
        ("0010", "0010"),
        ("", None),
        ("ABC", None),
        (None, None),
    ]

    all_ok = True
    for raw, expected in pairs:
        all_ok = _check_norm(raw, expected) and all_ok

    return all_ok


# Запуск


def main() -> None:
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║        Plate-number normalization smoke-tests          ║")
    print("╚══════════════════════════════════════════════════════════╝")

    results = [
        test_all_variants(),
        test_glued_region(),
        test_region_zero(),
        test_plain_and_edge_cases(),
    ]

    summarize(results)


if __name__ == "__main__":
    main()
