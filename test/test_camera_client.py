"""Юнит-тесты парсинга потока камеры: _resolve_boundary, _consume_parts, _handle_part."""

import queue

import pytest

from camera.camera_client import CameraListener

BOUNDARY = b"--myboundary"

EVENT_1 = b'{"TrafficCar":{"PlateNumber":"10010PC"}}'
EVENT_2 = b'{"TrafficCar":{"PlateNumber":"4414CE7"}}'

# Часть без Content-Length — как камера иногда шлёт пустые/небрежные части.


def _frameless_part(body: bytes) -> bytes:
    return BOUNDARY + b"\r\nContent-Type: text/plain\r\n\r\n" + body + b"\r\n"


def _listener() -> tuple[CameraListener, queue.Queue]:
    events: queue.Queue[str] = queue.Queue()
    listener = CameraListener(
        host="127.0.0.1:1",
        user="admin",
        password="12345678",
        codes=["TrafficJunction"],
        event_queue=events,
    )
    return listener, events


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
    assert _drain(events) == ["0010", "4414"]


def test_consume_parts_frameless_keeps_partial() -> None:
    listener, events = _listener()
    complete = _frameless_part(EVENT_1)
    partial = _frameless_part(EVENT_2)[:-4]  # обрезаем завершающий разделитель

    tail = listener._consume_parts(complete + partial, BOUNDARY)

    # Первая часть обработана, неготовый хвост сохранён без потерь.
    assert _drain(events) == ["0010"]
    assert tail == partial


# ---- _handle_part ----


def test_handle_part_normalizes_plate() -> None:
    listener, events = _listener()
    listener._handle_part(EVENT_1)

    assert _drain(events) == ["0010"]


def test_handle_part_skips_invalid_bodies() -> None:
    listener, events = _listener()
    listener._handle_part(b"")
    listener._handle_part(b"data=not-json-at-all")
    listener._handle_part(b'{"TrafficCar":{"PlateNumber":"ABC"}}')

    assert _drain(events) == []


def _drain(events: queue.Queue) -> list[str]:
    got = []
    while True:
        try:
            got.append(events.get_nowait())
        except queue.Empty:
            return got