"""Сквозные тесты приложения: окно App с in-memory БД и эмулятором камеры.

Окно прячется вызовом withdraw(), чтобы не мешать работе. Без дисплея
(например headless-CI) тесты пропускаются целиком.
"""

import queue
import time
from collections.abc import Callable

import pytest

from core.config import C
from core.database import Database
from test.camera_emulator import PASSWORD, USERNAME, CameraEmulator
from test.conftest import gui_available

pytestmark = pytest.mark.skipif(
    not gui_available(), reason="Нет дисплея — GUI-тесты пропущены"
)


@pytest.fixture
def app(monkeypatch):
    """App с in-memory БД и подменёнными настройками камеры; окно скрыто."""
    from ui.app import App

    monkeypatch.setattr("ui.app.load_settings", dict)
    monkeypatch.setattr("ui.app.save_settings", lambda *_args: None)

    window = App(db=Database(path=":memory:"))
    window.withdraw()
    yield window
    window._on_close()


def _poll_until(app, predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    """Вручную гонять опрос очереди камеры, пока предикат не выполнится."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app._poll_camera_queue()
        if predicate():
            return True
        time.sleep(0.05)
    return False


# ---- Сквозной контур: эмулятор камеры -> App -> БД ----


def test_camera_event_flows_to_db(app, monkeypatch) -> None:
    """Событие камеры через слушателя и _poll_camera_queue меняет статус ТС."""
    db: Database = app.db
    db.add_vehicle("ВС 0097-7")

    emulator = CameraEmulator()
    emulator.start()
    try:
        emulator.push_event("PC00970")
        monkeypatch.setattr("camera.camera_client._MIN_RECONNECT_DELAY", 0.05)
        app._start_camera_listener(emulator.host, USERNAME, PASSWORD)

        ok = _poll_until(
            app,
            lambda: dict(db.find_vehicle_by_number("0097")).get("status") == "arrived",
        )
        assert ok, "событие камеры не дошло до БД через приложение"
        assert app._camera_state == "connected"
    finally:
        emulator.stop()


def test_unknown_plate_keeps_db_untouched(app, monkeypatch) -> None:
    """Номер без ТС в базе мягко игнорируется, статусы не меняются."""
    db: Database = app.db
    db.add_vehicle("ВС 0097-7")
    was = db.get_vehicles()[0]["status"]

    emulator = CameraEmulator()
    emulator.start()
    try:
        emulator.push_event("0010ZZ")
        monkeypatch.setattr("camera.camera_client._MIN_RECONNECT_DELAY", 0.05)
        app._start_camera_listener(emulator.host, USERNAME, PASSWORD)

        # Ждём, пока слушатель подключится и заберёт событие из потока.
        time.sleep(0.6)
        app._poll_camera_queue()
        assert db.get_vehicles()[0]["status"] == was
    finally:
        emulator.stop()


# ---- Подключение/отключение камеры ----


def test_connect_camera_rejects_empty_host(app) -> None:
    assert app.connect_camera("   ", "u", "p") is False


def test_connect_camera_starts_listener(app, monkeypatch) -> None:
    """connect_camera сохраняет запись и запускает слушатель с очищенным host."""
    calls = []

    class StubListener:
        def __init__(self, host, user, password, codes, event_queue, status_queue):
            calls.append((host, user, password))

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr("ui.app.CameraListener", StubListener)

    assert app.connect_camera("http://10.0.0.1/", " admin ", "pw") is True
    assert calls == [("http://10.0.0.1", "admin", "pw")]
    assert app._camera_host == "http://10.0.0.1"


def test_stop_listener_clears_state(app) -> None:
    app._start_camera_listener("127.0.0.1:1", "u", "p")
    assert app._camera_polling is True

    app._stop_camera_listener()

    assert app._camera_listener is None
    assert app._camera_host == ""
    assert app._camera_state == ""
    # Флаг опроса самосбрасывается на следующем тике, когда слушателя нет.
    app._poll_camera_queue()
    assert app._camera_polling is False


def test_drain_camera_status_last_wins(app) -> None:
    app._camera_status_queue = queue.Queue()
    app._camera_status_queue.put("connected")
    app._camera_status_queue.put("error")

    app._drain_camera_status()

    assert app._camera_state == "error"


# ---- Навигация вкладок ----


def test_show_tab_highlights_navigation(app) -> None:
    app._show_tab("history")

    assert app._nav_buttons["history"].cget("fg_color") == C["card"]
    assert app._nav_buttons["accounting"].cget("fg_color") == "transparent"


def test_show_tab_refreshes_on_open(app, monkeypatch) -> None:
    hits: list[str] = []
    monkeypatch.setattr(app._tabs["stats"], "refresh", lambda: hits.append("stats"))

    app._show_tab("stats")

    assert hits == ["stats"]
