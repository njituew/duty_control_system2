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

import requests
from requests.auth import HTTPDigestAuth

from core.plates import normalize_plate_number

logger = logging.getLogger(__name__)

_CONTENT_LENGTH_RE = re.compile(rb"Content-Length:\s*(\d+)", re.IGNORECASE)
_BOUNDARY_RE = re.compile(r"boundary=(?:\"([^\"]+)\"|([^;\s]+))", re.IGNORECASE)
_PLATE_NUMBER_RE = re.compile(r'"PlateNumber"\s*:\s*"([^"\\]*)"')

_MIN_RECONNECT_DELAY = 3
_MAX_RECONNECT_DELAY = 60


def _extract_plate(body: bytes) -> str | None:
    """Извлекает TrafficCar.PlateNumber из одного тела мультипартного события.
    Каждая часть может быть либо сырым JSON, либо обёрткой, содержащей data=<json>.
    """
    text = body.decode("utf-8", errors="ignore").strip()
    if not text:
        logger.debug("Пустое тело события камеры")
        return None

    if "data=" in text:
        data_pos = text.find("data=")
        json_text = text[data_pos + len("data=") :].strip()
    else:
        json_text = text

    brace_start = json_text.find("{")
    if brace_start != -1:
        json_text = json_text[brace_start:]

    try:
        payload, _ = json.JSONDecoder().raw_decode(json_text)
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("Ожидался JSON-объект", json_text, 0)
        return payload.get("TrafficCar", {}).get("PlateNumber")
    except json.JSONDecodeError as exc:
        logger.debug(
            "Некорректный JSON события камеры, пробуем запасной вариант через регулярное выражение: %s; тело=%r",
            exc,
            json_text[:300],
        )

    match = _PLATE_NUMBER_RE.search(json_text)
    if match:
        plate = match.group(1)
        logger.info("Извлечён номер из некорректного JSON: %s", plate)
        return plate

    logger.warning(
        "Некорректный JSON события камеры, пропускаем; тело=%r",
        json_text[:300],
    )
    return None


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
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """Запускает фоновый поток-слушатель."""
        logger.info("Запуск потока слушателя камеры для host=%s", self._host)
        self._thread.start()

    def stop(self) -> None:
        """Сигнализирует слушателю об остановке и позволяет потоку завершиться."""
        logger.info("Остановка потока слушателя камеры")
        self._stop_event.set()

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
            start = buffer.find(boundary)
            if start == -1:
                return buffer

            headers_start = start + len(boundary)
            headers_end = buffer.find(b"\r\n\r\n", headers_start)
            if headers_end == -1:
                return buffer  # заголовки ещё не получены полностью

            header_block = buffer[headers_start:headers_end]
            length_match = _CONTENT_LENGTH_RE.search(header_block)
            body_start = headers_end + 4

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
        plate = _extract_plate(body)
        if not plate:
            logger.debug("Часть события камеры не содержала номерного знака")
            return
        number = normalize_plate_number(plate)
        if number:
            logger.info("Номер обнаружен: %s -> %s", plate, number)
            self._queue.put(number)
        else:
            logger.warning("Номер не содержит цифр: %s", plate)
