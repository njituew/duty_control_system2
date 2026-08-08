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
        (b'data={"TrafficCar":{"PlateNumber":"10010PC"}}', "10010PC"),
        (b'data={"Foo":{"Bar":1}}', None),
        (b'{"TrafficCar":{"PlateNumber":"0010PC1","Conf":', "0010PC1"),
        (b'{"TrafficCar":{"Other":1}}', None),
        (b'{"TrafficCar":"oops"}', None),
    ],
    ids=[
        "valid-json",
        "no-trafficcar",
        "json-array",
        "json-string",
        "empty",
        "garbage",
        "data-wrapper",
        "data-wrapper-no-car",
        "broken-json-regex-fallback",
        "no-platenumber",
        "trafficcar-not-dict",
    ],
)
def test_extract_plate(body: bytes, expected: str | None) -> None:
    """Разбор тела события: валидный JSON, обёртка data=, regex и мусор."""
    assert _extract_plate(body) == expected
