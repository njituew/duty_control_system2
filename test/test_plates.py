"""Смоук-тест извлечения номера из строки номерного знака."""

import sys

sys.path.insert(0, ".")

from plates import normalize_plate_number

# Вспомогательные функции


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


def check(raw: str, expected: str | None, label: str | None = None) -> bool:
    """Проверить один случай: нормализация raw должна дать expected."""
    got = normalize_plate_number(raw)
    desc = label or f"normalize({raw!r})"
    if got == expected:
        ok(f"{desc}  →  {got!r}")
        return True
    fail(f"{desc}  →  {got!r}, expected {expected!r}")
    return False


# Тест 1 — все варианты записи «0010 PC-1»


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
        all_ok = check(raw, "0010") and all_ok

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
        all_ok = check(raw, expected) and all_ok

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
        all_ok = check(raw, "0010") and all_ok

    return all_ok


# Тест 4 — обычный «1234 АВ 7» и крайние случаи


def test_plain_and_edge_cases() -> None:
    section("TEST 4 · Стандартный формат и крайние случаи")

    all_ok = True
    all_ok = check("1234 АВ 7", "1234") and all_ok
    all_ok = check("АВ 1234-7", "1234") and all_ok
    all_ok = check("РС 0001", "0001") and all_ok
    all_ok = check("0010", "0010") and all_ok
    all_ok = check("", None) and all_ok
    all_ok = check("ABC", None) and all_ok
    all_ok = check(None, None) and all_ok

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
