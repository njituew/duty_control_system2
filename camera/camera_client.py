"""Фоновый клиент для потока событий камеры Dahua ANPR.

Подключается к eventManager.cgi?action=attach и поддерживает соединение открытым,
анализируя мультипартный поток событий для распознанных номерных знаков и помещая
нормализованный основной номер каждого из них в очередь для использования интерфейсом.
"""

import json
import logging
import queue
import re
import threading
import time

import requests
from requests.auth import HTTPDigestAuth

from core.plates import normalize_plate_number

logger = logging.getLogger(__name__)

_CONTENT_LENGTH_RE = re.compile(rb"Content-Length:\s*(\d+)", re.IGNORECASE)
_BOUNDARY_RE = re.compile(r"boundary=(?:\"([^\"]+)\"|([^;\s]+))", re.IGNORECASE)
_PLATE_NUMBER_RE = re.compile(r'"PlateNumber"\s*:\s*"([^"\\]*)"')
_JUNCTION_DIRECTION_RE = re.compile(r'"JunctionDirection"\s*:\s*"([^"\\]*)"')
_DRIVING_DIRECTION_RE = re.compile(r'"DrivingDirection"\s*:\s*\[\s*"([^"\\]*)"')

_MIN_RECONNECT_DELAY = 3
_MAX_RECONNECT_DELAY = 60

# Защита от неограниченного роста буфера при невалидном потоке
# (заголовки без терминатора, мусор) вместо вечного зависания.
_MAX_BUFFER_BYTES = 2_000_000

# Окно дедупликации событий камеры (сек). Dahua ANPR может дублировать
# части мультипарт-потока; игнорируем повтор одного и того же (номер, направление)
# в пределах этого интервала.
_DEDUP_WINDOW_SECONDS = 5


def _extract_plate_and_direction(body: bytes) -> tuple[str | None, str | None]:
    """Извлекает TrafficCar.PlateNumber и направление движения из тела события.

    Returns:
        (plate_number, direction) где direction:
        - "arrival" если JunctionDirection == "Obverse" ИЛИ DrivingDirection[0] == "Approach"
        - "departure" если JunctionDirection == "Reverse" ИЛИ DrivingDirection[0] == "Leave"
        - None если направление не определено
    """
    text = body.decode("utf-8", errors="ignore").strip()
    if not text:
        logger.debug("Пустое тело события камеры")
        return None, None

    if "data=" in text:
        data_pos = text.find("data=")
        json_text = text[data_pos + len("data=") :].strip()
    else:
        json_text = text

    brace_start = json_text.find("{")
    if brace_start != -1:
        json_text = json_text[brace_start:]

    plate = None
    direction = None

    try:
        payload, _ = json.JSONDecoder().raw_decode(json_text)
        if isinstance(payload, dict):
            car = payload.get("TrafficCar")
            if isinstance(car, dict):
                plate = car.get("PlateNumber")

            # Определяем направление
            junction_dir = payload.get("JunctionDirection")
            driving_dir = payload.get("DrivingDirection")

            is_arrival = junction_dir == "Obverse" or (
                isinstance(driving_dir, list)
                and len(driving_dir) > 0
                and driving_dir[0] == "Approach"
            )
            is_departure = junction_dir == "Reverse" or (
                isinstance(driving_dir, list)
                and len(driving_dir) > 0
                and driving_dir[0] == "Leave"
            )

            if is_arrival:
                direction = "arrival"
            elif is_departure:
                direction = "departure"
    except json.JSONDecodeError as exc:
        logger.debug(
            "Некорректный JSON события камеры, пробуем запасной вариант через регулярное выражение: %s; тело=%r",
            exc,
            json_text[:300],
        )

    if plate is None:
        match = _PLATE_NUMBER_RE.search(json_text)
        if match:
            plate = match.group(1)
            logger.info("Извлечён номер из некорректного JSON: %s", plate)

        # Пробуем извлечь направление через regex
        if direction is None:
            jm = _JUNCTION_DIRECTION_RE.search(json_text)
            dm = _DRIVING_DIRECTION_RE.search(json_text)

            if jm:
                jd = jm.group(1)
                if jd == "Obverse":
                    direction = "arrival"
                elif jd == "Reverse":
                    direction = "departure"
            elif dm:
                dd = dm.group(1)
                if dd == "Approach":
                    direction = "arrival"
                elif dd == "Leave":
                    direction = "departure"

    if plate is None:
        logger.warning(
            "Некорректный JSON события камеры, пропускаем; тело=%r",
            json_text[:300],
        )

    return plate, direction


class CameraListener:
    """Запускает соединение с камерой в фоновом потоке.

    Переподключается с задержкой при любом сетевом сбое.
    Распознанные номера (уже нормализованные до основных цифр) помещаются в
    `event_queue`; вызывающий код читает их из главного потока через `.after()`.
    """

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        codes: list[str],
        event_queue: "queue.Queue[str]",
        status_queue: "queue.Queue[str] | None" = None,
        timeout: int = 30,
    ):
        self._host = host
        self._auth = HTTPDigestAuth(user, password)
        self._codes = codes
        self._queue = event_queue
        self._status_queue = status_queue
        self._timeout = timeout
        self._stop_event = threading.Event()
        self._last_emitted_status: str | None = None
        self._recent_events: dict[tuple[str, str], float] = {}
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """Запускает фоновый поток-слушатель."""
        logger.info("Запуск потока слушателя камеры для host=%s", self._host)
        self._thread.start()

    def stop(self) -> None:
        """Сигнализирует слушателю об остановке и позволяет потоку завершиться."""
        logger.info("Остановка потока слушателя камеры")
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        """Дождаться завершения фонового потока."""
        self._thread.join(timeout=timeout)

    def _attach_url(self) -> str:
        codes = ",".join(self._codes)
        return f"http://{self._host}/cgi-bin/eventManager.cgi?action=attach&codes=[{codes}]"

    def _emit_status(self, status: str) -> None:
        """Сообщить о смене состояния соединения в очередь статусов."""
        if self._status_queue is None or status == self._last_emitted_status:
            return
        self._last_emitted_status = status
        self._status_queue.put(status)

    def _run(self) -> None:
        delay = _MIN_RECONNECT_DELAY
        while not self._stop_event.is_set():
            try:
                self._listen_once()
                delay = _MIN_RECONNECT_DELAY  # сброс задержки
            except requests.RequestException as exc:
                logger.warning(
                    "Ошибка подключения к камере (%s), повтор через %s с",
                    exc,
                    delay,
                )
                self._emit_status("error")
            except Exception:
                logger.exception("Неожиданная ошибка в слушателе камеры")
                self._emit_status("error")
            if self._stop_event.wait(delay):
                return
            delay = min(delay * 2, _MAX_RECONNECT_DELAY)

    def _listen_once(self) -> None:
        response = requests.get(
            self._attach_url(),
            auth=self._auth,
            stream=True,
            timeout=(self._timeout, None),
        )
        response.raise_for_status()
        self._emit_status("connected")
        logger.info("Камера подключена к %s", self._attach_url())
        boundary = self._resolve_boundary(response.headers.get("Content-Type", ""))

        buffer = b""
        for chunk in response.iter_content(chunk_size=4096):
            if self._stop_event.is_set():
                response.close()
                return
            if not chunk:
                continue
            buffer += chunk
            buffer = self._consume_parts(buffer, boundary)

    @staticmethod
    def _resolve_boundary(content_type: str) -> bytes:
        match = _BOUNDARY_RE.search(content_type)
        if match:
            boundary = match.group(1) or match.group(2)
            if boundary:
                boundary = boundary.strip()
            else:
                boundary = "myboundary"
        else:
            boundary = "myboundary"
        boundary = boundary.removeprefix("--")
        return f"--{boundary}".encode()

    def _consume_parts(self, buffer: bytes, boundary: bytes) -> bytes:
        """Извлекает каждую завершённую часть из буфера, возвращает необработанный хвост."""
        while True:
            if len(buffer) > _MAX_BUFFER_BYTES:
                raise RuntimeError(
                    f"Буфер потока камеры превысил лимит ({_MAX_BUFFER_BYTES} байт)"
                )

            start = buffer.find(boundary)
            if start == -1:
                return buffer

            headers_start = start + len(boundary)
            # Конец заголовков: CRLF (штатно) или голый LF (некоторые прошивки).
            crlf_end = buffer.find(b"\r\n\r\n", headers_start)
            lf_end = buffer.find(b"\n\n", headers_start)
            if crlf_end == -1:
                headers_end, term_len = lf_end, 2
            elif lf_end == -1 or crlf_end < lf_end:
                headers_end, term_len = crlf_end, 4
            else:
                headers_end, term_len = lf_end, 2
            if headers_end == -1:
                return buffer  # заголовки ещё не получены полностью

            header_block = buffer[headers_start:headers_end]
            length_match = _CONTENT_LENGTH_RE.search(header_block)
            body_start = headers_end + term_len

            if length_match:
                body_length = int(length_match.group(1))
                body_end = body_start + body_length
                if len(buffer) < body_end:
                    return buffer  # тело ещё не получено полностью
                self._handle_part(buffer[body_start:body_end])
                buffer = buffer[body_end:]
                continue

            # Запасной вариант, если Content-Length отсутствует.
            next_boundary = buffer.find(boundary, body_start)
            if next_boundary == -1:
                return buffer
            body_end = next_boundary
            if body_end >= 2 and buffer[body_end - 2 : body_end] == b"\r\n":
                body_end -= 2
            self._handle_part(buffer[body_start:body_end])
            buffer = buffer[next_boundary:]

    def _handle_part(self, body: bytes) -> None:
        plate, direction = _extract_plate_and_direction(body)
        if not plate:
            logger.debug("Часть события камеры не содержала номерного знака")
            return
        number = normalize_plate_number(plate)
        if not number:
            logger.warning("Номер не содержит цифр: %s", plate)
            return

        now = time.monotonic()
        key = (number, direction or "")
        last_seen = self._recent_events.get(key)
        if last_seen is not None and (now - last_seen) < _DEDUP_WINDOW_SECONDS:
            logger.debug(
                "Дубль события камеры пропущен: %s -> %s, direction=%s",
                plate,
                number,
                direction,
            )
            return

        self._recent_events[key] = now
        # Очистка устаревших записей, чтобы словарь не рос бесконечно.
        if len(self._recent_events) > 500:
            cutoff = now - _DEDUP_WINDOW_SECONDS
            self._recent_events = {
                k: v for k, v in self._recent_events.items() if v >= cutoff
            }

        logger.info(
            "Номер обнаружен: %s -> %s, direction=%s", plate, number, direction
        )
        self._queue.put((number, direction))
