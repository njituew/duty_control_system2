"""Смоук-тест разбора тел событий камеры в _extract_plate."""

import sys

sys.path.insert(0, ".")

from harness import check, section, summarize
from camera.camera_client import _extract_plate


# Тест 1 — валидный JSON и запасной вариант через regex


def test_valid_and_fallback() -> None:
    section("TEST 1 · Валидный JSON и запасной вариант через regex")

    ok_js = check(
        _extract_plate(b'{"TrafficCar":{"PlateNumber":"10010PC"}}') == "10010PC",
        "extracts PlateNumber from valid JSON",
    )

    ok_no_trafficcar = check(
        _extract_plate(b'{"Foo":{"Bar":1}}') is None,
        "JSON without TrafficCar returns None",
    )

    return ok_js and ok_no_trafficcar


# Тест 2 — некорректные тела: не-dict JSON и пустые строки


def test_malformed_bodies() -> None:
    section("TEST 2 · Некорректные тела: не-dict JSON, пустые строки")

    ok_list = check(
        _extract_plate(b'[1,2,3]') is None,
        "JSON-array body returns None (regex fallback, no crash)",
    )

    ok_scalar = check(
        _extract_plate(b'"plain string"') is None,
        "JSON-string body returns None (regex fallback, no crash)",
    )

    ok_empty = check(
        _extract_plate(b"") is None, "empty body returns None"
    )

    ok_garbage = check(
        _extract_plate(b"data=not-json-at-all") is None,
        "garbage body returns None",
    )

    return ok_list and ok_scalar and ok_empty and ok_garbage


# Запуск


def main() -> None:
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║        Camera event-body parsing smoke-tests            ║")
    print("╚══════════════════════════════════════════════════════════╝")

    results = [
        test_valid_and_fallback(),
        test_malformed_bodies(),
    ]

    summarize(results)


if __name__ == "__main__":
    main()