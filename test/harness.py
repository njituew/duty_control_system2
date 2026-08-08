"""Общие вспомогательные функции для standalone-смоук-тестов."""

import sys


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


def check(cond: bool, label: str, detail: str = "") -> bool:
    if cond:
        ok(label)
        return True
    fail(label, detail)
    return False


def raises(exc_type: type[BaseException], fn, label: str) -> bool:
    """Проверить, что при вызове fn() бросается исключение exc_type."""
    try:
        fn()
    except exc_type:
        ok(label)
        return True
    except Exception as e:  # noqa: BLE001
        fail(label, f"raised {type(e).__name__}: {e} (expected {exc_type.__name__})")
        return False
    fail(label, "no exception raised")
    return False


def summarize(results: list[bool]) -> None:
    """Напечатать итог прогона и завершиться с соответствующим кодом."""
    passed = sum(1 for r in results if r)
    total = len(results)

    print(f"\n{'═' * 60}")
    if passed == total:
        print(f"  \033[32m✓ All {total} tests passed\033[0m")
    else:
        print(f"  \033[31m✗ {total - passed} of {total} tests FAILED\033[0m")
    print(f"{'═' * 60}\n")

    sys.exit(0 if passed == total else 1)