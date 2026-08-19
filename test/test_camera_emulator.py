"""Интеграционные тесты «приложение ↔ эмулятор камеры».

Эмулятор (test/camera_emulator.py) поднимает на 127.0.0.1:0 настоящий
HTTP-сервер с тем же протоколом, что и реальная камера DHI-ITU:
Digest-аутентификация и multipart/x-mixed-replace поток на eventManager.cgi.
Проверяется, что CameraListener проходит рукопожатие, разбирает части
событий камеры, нормализует номера в очередь приложения и доводит их
до переключения статуса ТС в БД.
"""

import queue
import time
from collections.abc import Iterator

import pytest
import requests
from requests.auth import HTTPDigestAuth

from camera.camera_client import CameraListener
from core.config import CAMERA_EVENT_CODES
from test.camera_emulator import PASSWORD, USERNAME, CameraEmulator

ATTACH_URL = "/cgi-bin/eventManager.cgi?action=attach&codes=[TrafficJunction]"


@pytest.fixture
def emulator() -> Iterator[CameraEmulator]:
    """Сервер-эмулятор камеры на эфемерном порту; гасится после теста."""
    server = CameraEmulator()
    server.start()
    yield server
    server.stop()


def _make_listener(emulator: CameraEmulator, monkeypatch: pytest.MonkeyPatch):
    """Listener с быстрым переподключением и двумя пустыми очередями."""
    monkeypatch.setattr("camera.camera_client._MIN_RECONNECT_DELAY", 0.05)
    events: queue.Queue[str] = queue.Queue()
    statuses: queue.Queue[str] = queue.Queue()
    listener = CameraListener(
        host=emulator.host,
        user=USERNAME,
        password=PASSWORD,
        codes=CAMERA_EVENT_CODES,
        event_queue=events,
        status_queue=statuses,
    )
    return listener, events, statuses


def _drain_timeout(
    events: queue.Queue, expected: int, timeout: float = 3.0
) -> list[str]:
    """Собрать из очереди до `expected` элементов в пределах таймаута."""
    got: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(got) < expected:
        try:
            got.append(events.get(timeout=0.2))
        except queue.Empty:
            continue
    return got


# ---- Сквозной приём событий камеры ----


def test_receives_normalized_plates_from_camera(emulator, monkeypatch) -> None:
    """Камера шлёт реальные номера — очередь получает основные цифры."""
    emulator.push_event("PC00970")  # из белого списка камеры
    emulator.push_event("4414CE7")  # из белого списка камеры
    emulator.push_event("10010PC")  # слепой знак из реального потока

    listener, events, _ = _make_listener(emulator, monkeypatch)
    listener.start()
    try:
        got = _drain_timeout(events, expected=3)
    finally:
        listener.stop()

    assert got == ["0097", "4414", "0010"]


def test_reports_connected_status(emulator, monkeypatch) -> None:
    """Listener подтверждает подключение к камере через очередь статусов."""
    listener, _, statuses = _make_listener(emulator, monkeypatch)
    listener.start()
    try:
        assert statuses.get(timeout=3) == "connected"
    finally:
        listener.stop()


def test_report_connected_status_emitted_once(emulator, monkeypatch) -> None:
    """Status 'connected' приходит один раз и не дублируется без сбоев."""
    listener, _, statuses = _make_listener(emulator, monkeypatch)
    listener.start()
    try:
        assert statuses.get(timeout=3) == "connected"
        with pytest.raises(queue.Empty):
            statuses.get(timeout=0.3)
    finally:
        listener.stop()


def test_attach_uses_chunked_transfer_encoding(emulator) -> None:
    """Поток события передаётся чанками (HTTP/1.1 + Transfer-Encoding)."""
    url = f"http://{emulator.host}{ATTACH_URL}"
    response = requests.get(
        url, auth=HTTPDigestAuth(USERNAME, PASSWORD), timeout=3, stream=True
    )
    try:
        assert response.status_code == 200
        assert response.raw.chunked is True
    finally:
        response.close()


def test_event_pipeline_updates_vehicle_status(emulator, db, monkeypatch) -> None:
    """Событие камеры -> очередь -> переключение статуса ТС в БД."""
    db.add_vehicle("ВС 0097-7")  # нормализованный номер = "0097"

    emulator.push_event("PC00970")

    listener, events, _ = _make_listener(emulator, monkeypatch)
    listener.start()
    try:
        number = events.get(timeout=3)
    finally:
        listener.stop()

    assert number == "0097"
    assert db.find_vehicle_by_number(number)["status"] == "idle"

    vehicle = db.toggle_vehicle_status_by_number(number)
    assert vehicle["status"] == "arrived"
    assert db.find_vehicle_by_number("ВС 0097-7")["status"] == "arrived"


# ---- Контракт сервера (такой же, как у настоящей камеры) ----


def test_rejects_wrong_credentials(emulator) -> None:
    """Неверный пароль — камера отвечает 401 с Digest-челленджем."""
    url = f"http://{emulator.host}{ATTACH_URL}"
    response = requests.get(
        url, auth=HTTPDigestAuth(USERNAME, "wrong_password"), timeout=3
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Digest realm=")


def test_rejects_invalid_attach_params(emulator) -> None:
    """Неверные action/codes — камера отвечает 400."""
    url = f"http://{emulator.host}{ATTACH_URL}"
    bad_url = url.replace("codes=[TrafficJunction]", "codes=[WrongCode]")
    auth = HTTPDigestAuth(USERNAME, PASSWORD)
    assert requests.get(bad_url, auth=auth, timeout=3).status_code == 400

    bad_action = url.replace("action=attach", "action=nope")
    assert requests.get(bad_action, auth=auth, timeout=3).status_code == 400


def test_attach_returns_consistent_body(emulator) -> None:
    """Ответ на attach содержит границу мультипарт-потока."""
    url = f"http://{emulator.host}{ATTACH_URL}"
    response = requests.get(
        url, auth=HTTPDigestAuth(USERNAME, PASSWORD), timeout=3, stream=True
    )
    assert response.status_code == 200
    assert (
        response.headers["Content-Type"]
        == "multipart/x-mixed-replace; boundary=myboundary"
    )
    response.close()


# ---- Устойчивость к невалидным событиям ----


def test_garbage_events_are_skipped(emulator, monkeypatch) -> None:
    """Мусорные части не ломают поток и не попадают в очередь."""
    emulator.push_raw(b"data=not-json-at-all")
    emulator.push_event("PC00970")
    emulator.push_raw(b"")

    listener, events, _ = _make_listener(emulator, monkeypatch)
    listener.start()
    try:
        got = _drain_timeout(events, expected=1)
    finally:
        listener.stop()

    # Валидное событие прошло, мусор проглочен слушателем
    assert got == ["0097"]


def test_accepts_lf_framed_parts(emulator, monkeypatch) -> None:
    """Другая прошивка шлёт части с LF-заголовками — события всё равно доходят."""
    emulator.lf_headers = True
    emulator.push_event("PC00970")

    listener, events, _ = _make_listener(emulator, monkeypatch)
    listener.start()
    try:
        assert events.get(timeout=3) == "0097"
    finally:
        listener.stop()


# ---- Переподключение ----


def test_reconnects_after_server_restart(emulator, monkeypatch) -> None:
    """Падение камеры -> статус error, перезапуск -> снова события."""
    listener, events, statuses = _make_listener(emulator, monkeypatch)
    listener.start()

    emulator.push_event("PC00970")
    assert events.get(timeout=3) == "0097"

    # Глушим сервер: listener уходит в error на следующей попытке
    emulator.stop()

    now = time.time()
    while time.time() - now < 2.0:
        try:
            if statuses.get(timeout=0.2) == "error":
                break
        except queue.Empty:
            continue
    else:
        pytest.fail("статус error не пришёл после остановки камеры")

    # Поднимаем новый сервер на том же порту — соединение восстанавливается
    restarted = CameraEmulator(host="127.0.0.1", port=emulator.port)
    restarted.start()
    try:
        restarted.push_event("4414CE7")
        assert events.get(timeout=3) == "4414"
    finally:
        restarted.stop()
        listener.stop()
