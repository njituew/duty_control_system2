"""Тесты разбора тел событий камеры в camera.camera_client._extract_plate."""

import pytest

from camera.camera_client import _extract_plate


@pytest.mark.parametrize(
    "body,expected",
    [
        (b'{"TrafficCar":{"PlateNumber":"10010PC"}}', "10010PC"),
        (b'{"Foo":{"Bar":1}}', None),
        (b"[1,2,3]", None),
        (b'"plain string"', None),
        (b"", None),
        (b"data=not-json-at-all", None),
    ],
    ids=[
        "valid-json",
        "no-trafficcar",
        "json-array",
        "json-string",
        "empty",
        "garbage",
    ],
)
def test_extract_plate(body: bytes, expected: str | None) -> None:
    """Разбор тела события: валидный JSON, запасной regex и мусор."""
    assert _extract_plate(body) == expected
