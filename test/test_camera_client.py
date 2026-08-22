"""Юнит-тесты парсинга потока камеры: _resolve_boundary, _consume_parts, _handle_part."""

import queue

import pytest

from camera.camera_client import CameraListener, _extract_plate_and_direction

BOUNDARY = b"--myboundary"

EVENT_1 = b'{"TrafficCar":{"PlateNumber":"10010PC"}}'
EVENT_2 = b'{"TrafficCar":{"PlateNumber":"4414CE7"}}'

# События с направлением прибытия
EVENT_ARRIVAL_OBVERSE = (
    b'{"JunctionDirection":"Obverse","TrafficCar":{"PlateNumber":"1234"}}'
)
EVENT_ARRIVAL_APPROACH = (
    b'{"DrivingDirection":["Approach","",""],"TrafficCar":{"PlateNumber":"5678"}}'
)

# События с направлением убытия
EVENT_DEPARTURE_REVERSE = (
    b'{"JunctionDirection":"Reverse","TrafficCar":{"PlateNumber":"9012"}}'
)
EVENT_DEPARTURE_LEAVE = (
    b'{"DrivingDirection":["Leave","",""],"TrafficCar":{"PlateNumber":"3456"}}'
)

# Событие без направления
EVENT_NO_DIRECTION = b'{"TrafficCar":{"PlateNumber":"7777"}}'

# Часть без Content-Length — как камера иногда шлёт пустые/небрежные части.


def _frameless_part(body: bytes) -> bytes:
    return BOUNDARY + b"\r\nContent-Type: text/plain\r\n\r\n" + body + b"\r\n"


def _listener() -> tuple[CameraListener, queue.Queue]:
    events: queue.Queue[tuple[str, str | None]] = queue.Queue()
    listener = CameraListener(
        host="127.0.0.1:1",
        user="admin",
        password="12345678",
        codes=["TrafficJunction"],
        event_queue=events,
    )
    return listener, events


# ---- _extract_plate_and_direction ----


@pytest.mark.parametrize(
    "body,expected_plate,expected_direction",
    [
        (EVENT_1, "10010PC", None),
        (EVENT_2, "4414CE7", None),
        (EVENT_ARRIVAL_OBVERSE, "1234", "arrival"),
        (EVENT_ARRIVAL_APPROACH, "5678", "arrival"),
        (EVENT_DEPARTURE_REVERSE, "9012", "departure"),
        (EVENT_DEPARTURE_LEAVE, "3456", "departure"),
        (EVENT_NO_DIRECTION, "7777", None),
    ],
    ids=[
        "basic",
        "basic-2",
        "arrival-junction-obverse",
        "arrival-driving-approach",
        "departure-junction-reverse",
        "departure-driving-leave",
        "no-direction",
    ],
)
def test_extract_plate_and_direction(
    body: bytes, expected_plate: str, expected_direction: str | None
) -> None:
    plate, direction = _extract_plate_and_direction(body)
    assert plate == expected_plate
    assert direction == expected_direction


# ---- _resolve_boundary ----


@pytest.mark.parametrize(
    "content_type,expected",
    [
        ('multipart/x-mixed-replace; boundary="quoted"', b"--quoted"),
        ("multipart/x-mixed-replace; boundary=unquoted", b"--unquoted"),
        ('multipart/x-mixed-replace; boundary="--with-dashes"', b"--with-dashes"),
        ("text/plain", b"--myboundary"),
    ],
    ids=["quoted", "unquoted", "dashes-stripped", "default"],
)
def test_resolve_boundary(content_type: str, expected: bytes) -> None:
    assert CameraListener._resolve_boundary(content_type) == expected


# ---- _consume_parts (без Content-Length) ----


def test_consume_parts_frameless_handles_all() -> None:
    listener, events = _listener()
    # Каждая часть завершается следующим разделителем; финишный — в конце потока.
    buffer = _frameless_part(EVENT_1) + _frameless_part(EVENT_2) + BOUNDARY

    tail = listener._consume_parts(buffer, BOUNDARY)

    # Закрывающий разделитель без тела остаётся в буфере: клиент ждёт
    # заголовков следующей части, пока поток сам не завершится.
    assert tail == BOUNDARY
    assert _drain(events) == [("0010", None), ("4414", None)]


def test_consume_parts_frameless_keeps_partial() -> None:
    listener, events = _listener()
    complete = _frameless_part(EVENT_1)
    partial = _frameless_part(EVENT_2)[:-4]  # обрезаем завершающий разделитель

    tail = listener._consume_parts(complete + partial, BOUNDARY)

    # Первая часть обработана, неготовый хвост сохранён без потерь.
    assert _drain(events) == [("0010", None)]
    assert tail == partial


# ---- _consume_parts (заголовки с голыми LF — другая прошивка камеры) ----


def _lf_part(body: bytes) -> bytes:
    """Часть, где заголовки заканчиваются \n\n вместо \r\n\r\n."""
    return (
        BOUNDARY
        + b"\n"
        + b"Content-Type: text/plain\nContent-Length: "
        + str(len(body)).encode()
        + b"\n\n"
        + body
        + b"\n"
    )


def test_consume_parts_lf_headers_handles_all() -> None:
    listener, events = _listener()
    buffer = _lf_part(EVENT_1) + _lf_part(EVENT_2)

    tail = listener._consume_parts(buffer, BOUNDARY)

    assert _drain(events) == [("0010", None), ("4414", None)]
    assert tail == b"\n"


def test_consume_parts_lf_and_crlf_mixed() -> None:
    """LF-часть и CRLF-часть в одном потоке разбираются корректно."""
    listener, events = _listener()
    buffer = _lf_part(EVENT_1) + _frameless_part(EVENT_2) + BOUNDARY

    tail = listener._consume_parts(buffer, BOUNDARY)

    assert _drain(events) == [("0010", None), ("4414", None)]
    assert tail == BOUNDARY


def test_consume_parts_raises_after_buffer_limit(monkeypatch) -> None:
    """Заголовки без терминатора накапливаются, но не вечно: растёт буфер —
    исключение вместо зависания (цикл переподключения получает 'error')."""
    monkeypatch.setattr("camera.camera_client._MAX_BUFFER_BYTES", 64)
    listener, _ = _listener()
    part = BOUNDARY + b"\nContent-Type: text/plain\n" + b"padding-13"

    tail = listener._consume_parts(part, BOUNDARY)
    assert tail == part  # хвост без терминатора сохранён

    with pytest.raises(RuntimeError):
        listener._consume_parts(tail + b"x" * 40, BOUNDARY)


# ---- _handle_part ----


def test_handle_part_normalizes_plate() -> None:
    listener, events = _listener()
    listener._handle_part(EVENT_1)

    assert _drain(events) == [("0010", None)]


def test_handle_part_with_arrival_direction() -> None:
    listener, events = _listener()
    listener._handle_part(EVENT_ARRIVAL_OBVERSE)

    assert _drain(events) == [("1234", "arrival")]


def test_handle_part_with_departure_direction() -> None:
    listener, events = _listener()
    listener._handle_part(EVENT_DEPARTURE_REVERSE)

    assert _drain(events) == [("9012", "departure")]


def test_handle_part_skips_invalid_bodies() -> None:
    listener, events = _listener()
    listener._handle_part(b"")
    listener._handle_part(b"data=not-json-at-all")
    listener._handle_part(b'{"TrafficCar":{"PlateNumber":"ABC"}}')

    assert _drain(events) == []


def _drain(events: queue.Queue) -> list[tuple[str, str | None]]:
    got = []
    while True:
        try:
            got.append(events.get_nowait())
        except queue.Empty:
            return got
