"""Тесты разбора тел событий камеры в camera.camera_client._extract_plate_and_direction."""

import pytest

from camera.camera_client import _extract_plate_and_direction


@pytest.mark.parametrize(
    "body,expected_plate,expected_direction",
    [
        (b'{"TrafficCar":{"PlateNumber":"10010PC"}}', "10010PC", None),
        (b'{"Foo":{"Bar":1}}', None, None),
        (b"[1,2,3]", None, None),
        (b'"plain string"', None, None),
        (b"", None, None),
        (b"data=not-json-at-all", None, None),
        (b'data={"TrafficCar":{"PlateNumber":"10010PC"}}', "10010PC", None),
        (b'data={"Foo":{"Bar":1}}', None, None),
        (b'{"TrafficCar":{"PlateNumber":"0010PC1","Conf":', "0010PC1", None),
        (b'{"TrafficCar":{"Other":1}}', None, None),
        (b'{"TrafficCar":"oops"}', None, None),
        # Tests with direction
        (b'{"JunctionDirection":"Obverse","TrafficCar":{"PlateNumber":"1234"}}', "1234", "arrival"),
        (b'{"DrivingDirection":["Approach","",""],"TrafficCar":{"PlateNumber":"5678"}}', "5678", "arrival"),
        (b'{"JunctionDirection":"Reverse","TrafficCar":{"PlateNumber":"9012"}}', "9012", "departure"),
        (b'{"DrivingDirection":["Leave","",""],"TrafficCar":{"PlateNumber":"3456"}}', "3456", "departure"),
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
        "arrival-junction-obverse",
        "arrival-driving-approach",
        "departure-junction-reverse",
        "departure-driving-leave",
    ],
)
def test_extract_plate_and_direction(body: bytes, expected_plate: str | None, expected_direction: str | None) -> None:
    """Разбор тела события: валидный JSON, обёртка data=, regex и мусор."""
    plate, direction = _extract_plate_and_direction(body)
    assert plate == expected_plate
    assert direction == expected_direction
