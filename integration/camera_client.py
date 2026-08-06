"""Background client for the Dahua ANPR camera event stream.

Connects to eventManager.cgi?action=attach and keeps the connection open,
parsing the multipart event stream for recognised plate numbers and pushing
the normalised main number of each one onto a queue for the UI to consume.
"""

import json
import logging
import queue
import re
import threading

import requests
from requests.auth import HTTPDigestAuth

logger = logging.getLogger(__name__)

_CONTENT_LENGTH_RE = re.compile(rb"Content-Length:\s*(\d+)", re.IGNORECASE)
_BOUNDARY_RE = re.compile(r"boundary=(?:\"([^\"]+)\"|([^;\s]+))", re.IGNORECASE)
_PLATE_NUMBER_RE = re.compile(r'"PlateNumber"\s*:\s*"([^"\\]*)"')

_MIN_RECONNECT_DELAY = 3
_MAX_RECONNECT_DELAY = 60


def normalize_plate(plate: str) -> str | None:
    """Extract the main number from a plate string, e.g. 'PC0097' -> '0097'.

    Belarusian plates carry letters plus a digit block; only the digits are
    used to match vehicles in the database. Returns None if no digits found.
    """
    match = re.search(r"\d+", plate)
    return match.group(0) if match else None


def _extract_plate(body: bytes) -> str | None:
    """Pull TrafficCar.PlateNumber out of one multipart event body.

    Each part may be either raw JSON or a wrapper containing data=<json>.
    """
    text = body.decode("utf-8", errors="ignore").strip()
    if not text:
        logger.debug("Empty camera event body")
        return None

    if "data=" in text:
        data_pos = text.find("data=")
        json_text = text[data_pos + len("data=") :].strip()
    else:
        json_text = text

    brace_start = json_text.find("{")
    if brace_start != -1:
        json_text = json_text[brace_start:]

    # Some camera/emulator payloads append non-JSON trailer text after the
    # actual object, especially in multipart streams. Try exact JSON parse first,
    # and fall back to plate-number extraction if the object is otherwise valid.
    try:
        payload, _ = json.JSONDecoder().raw_decode(json_text)
        return payload.get("TrafficCar", {}).get("PlateNumber")
    except json.JSONDecodeError as exc:
        logger.debug(
            "Malformed camera event JSON, trying regex fallback: %s; body=%r",
            exc,
            json_text[:300],
        )

    match = _PLATE_NUMBER_RE.search(json_text)
    if match:
        plate = match.group(1)
        logger.info("Extracted plate from malformed JSON payload: %s", plate)
        return plate

    logger.warning(
        "Malformed camera event JSON, skipping: %s; body=%r",
        exc,
        json_text[:300],
    )
    return None


class CameraListener:
    """Runs the camera connection on a background thread.

    Reconnects with exponential backoff on any network failure. Recognised
    plate numbers (already normalised to their main digits) are put onto
    `event_queue`; the caller reads them from the main thread via `.after()`.
    """

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        codes: list[str],
        event_queue: "queue.Queue[str]",
        timeout: int = 30,
    ):
        self._host = host
        self._auth = HTTPDigestAuth(user, password)
        self._codes = codes
        self._queue = event_queue
        self._timeout = timeout
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """Start the background listener thread."""
        logger.info("Starting camera listener thread for host=%s", self._host)
        self._thread.start()

    def stop(self) -> None:
        """Signal the listener to stop and let the thread exit."""
        logger.info("Stopping camera listener thread")
        self._stop_event.set()

    def _attach_url(self) -> str:
        codes = ",".join(self._codes)
        return f"http://{self._host}/cgi-bin/eventManager.cgi?action=attach&codes=[{codes}]"

    def _run(self) -> None:
        delay = _MIN_RECONNECT_DELAY
        while not self._stop_event.is_set():
            try:
                self._listen_once()
                delay = _MIN_RECONNECT_DELAY  # connection was healthy, reset backoff
            except requests.RequestException as exc:
                logger.warning(
                    "Camera connection failed (%s), retrying in %ss",
                    exc,
                    delay,
                )
            except Exception:
                logger.exception("Unexpected error in camera listener")
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
        logger.info("Camera connected to %s", self._attach_url())
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
        """Pull out every complete part from buffer, return the unparsed tail."""
        while True:
            start = buffer.find(boundary)
            if start == -1:
                return buffer

            headers_start = start + len(boundary)
            headers_end = buffer.find(b"\r\n\r\n", headers_start)
            if headers_end == -1:
                return buffer  # headers not fully received yet

            header_block = buffer[headers_start:headers_end]
            length_match = _CONTENT_LENGTH_RE.search(header_block)
            body_start = headers_end + 4

            if length_match:
                body_length = int(length_match.group(1))
                body_end = body_start + body_length
                if len(buffer) < body_end:
                    return buffer  # body not fully received yet
                self._handle_part(buffer[body_start:body_end])
                buffer = buffer[body_end:]
                continue

            # Fallback when Content-Length is not available.
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
            logger.debug("Camera event part contained no plate number")
            return
        number = normalize_plate(plate)
        if number:
            logger.info("Plate seen: %s -> %s", plate, number)
            self._queue.put(number)
        else:
            logger.warning("Plate contains no digits: %s", plate)
