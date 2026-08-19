"""Эмулятор камеры DHI-ITU-T (ANPR) для интеграционных тестов.

Повторяет протокол реальной камеры:
- HTTP Digest-аутентификация: 401 + WWW-Authenticate (realm, qop="auth",
  nonce, opaque), проверка строго возрастающего nc;
- GET /cgi-bin/eventManager.cgi?action=attach&codes=[TrafficJunction] ->
  multipart/x-mixed-replace поток, части в формате камеры
  (Code=TrafficJunction;action=Pulse;index=0;data=<json с TrafficCar.PlateNumber>);
- неверные параметры attach -> 400.

Сервер на чистой stdlib (http.server), без внешних зависимостей.
Запускается в собственном потоке: start()/stop(). События подаются через
push_event() (полное событие камеры) или push_raw() (произвольное тело части).
Генерация событий детерминированная: фиксированное зерно RNG.
"""

import hashlib
import http.server
import json
import queue
import random
import re
import threading
import time
import urllib.parse

USERNAME = "admin"
PASSWORD = "12345678"
REALM = "test"
BOUNDARY = "myboundary"
ATTACH_PATH = "/cgi-bin/eventManager.cgi"

# Номера из белого списка — камера шлёт полностью заполненный WhiteList
WHITE_LIST_PLATES = {"4414CE7", "PC00970"}


def _md5(value: str) -> str:
    """MD5 в hex — как считает алгоритм Digest (qop=auth)."""
    return hashlib.md5(value.encode()).hexdigest()


def _parse_digest(auth_value: str) -> dict[str, str]:
    """Разобрать параметры Digest-заголовка (в кавычках и без)."""
    body = auth_value[7:]  # убираем "Digest "
    params: dict[str, str] = {}
    for key, value in re.findall(r'(\w+)="([^"]*)"', body):
        params[key] = value
    for key, value in re.findall(r"(\w+)=([^,\s]+)", body):
        if key not in params:
            params[key] = value
    return params


class CameraEmulator(http.server.ThreadingHTTPServer):
    """Threading-HTTP-сервер, реализующий attach-протокол камеры.

    Поднимается на 127.0.0.1:0 (эфемерный порт). Полезные поля и методы:
    host — "127.0.0.1:<порт>" для CameraListener; push_event(plate, ...) —
    полное событие камеры; push_raw(body) — произвольное тело части.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str = "127.0.0.1", port: int = 0, seed: int = 42):
        super().__init__((host, port), _CameraHandler)
        self.camera = self  # handler обращается через self.server.camera

        self._rng = random.Random(seed)
        self._nonce_store: dict[str, dict] = {}
        self._nonces_lock = threading.Lock()
        self._events: queue.Queue[bytes] = queue.Queue()
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None

        # Счётчики события: продолжаем с тех значений, что у реальной камеры
        self._event_counter = 0
        self._group_counter = 45103734
        self._object_counter = 7483
        self._frame_seq = 134665
        self._encode_seq = 360710337
        self._pts_counter = 42960639840.0
        self._real_utc_base = 1785762816

        # True — слать части с LF-заголовками (другая прошивка камеры).
        self.lf_headers = False

    # ---- Жизненный цикл ----

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def host(self) -> str:
        """host:port — ровно тот вид, который ждёт CameraListener."""
        return f"127.0.0.1:{self.server_address[1]}"

    def start(self) -> None:
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Останавливает accept-цикл и стримы всех активных подключений."""
        self._stop_flag.set()
        self.shutdown()
        self.server_close()

    # ---- Подача событий ----

    def push_event(
        self,
        plate: str,
        country: str = "PSE",
        color: str = "Blue",
        sign: str = "Unknown",
        trust_car: bool | None = None,
    ) -> None:
        """Собрать полное событие камеры и положить его в очередь отправки."""
        event = self.generate_event(plate, country, color, sign, trust_car)
        body = (
            f"Code=TrafficJunction;action=Pulse;index=0;data="
            f"{json.dumps(event, ensure_ascii=False, indent=3)}"
        ).encode()
        self._events.put(body)

    def push_raw(self, body: bytes) -> None:
        """Поставить в очередь произвольное тело части (для пограничных тестов)."""
        self._events.put(body)

    # ---- Digest-аутентификация (как у реальной камеры) ----

    def issue_nonce(self) -> str:
        nonce = _md5(f"{time.time()}{self._rng.random()}{id(self)}")
        with self._nonces_lock:
            self._nonce_store[nonce] = {"nc": 0, "created": time.time()}
        return nonce

    def digest_challenge(self) -> str:
        return (
            f'Digest realm="{REALM}", qop="auth", '
            f'nonce="{self.issue_nonce()}", opaque="{_md5(REALM)}"'
        )

    def authorized(self, auth_header: str | None, method: str, uri: str) -> bool:
        """Полная проверка Digest-заголовка с учётом nc и nonce."""
        if not auth_header or not auth_header.startswith("Digest "):
            return False

        params = _parse_digest(auth_header)
        required = {
            "username",
            "realm",
            "nonce",
            "uri",
            "response",
            "nc",
            "cnonce",
            "qop",
        }
        if not required.issubset(params.keys()):
            return False
        if params["username"] != USERNAME or params["realm"] != REALM:
            return False

        nonce = params["nonce"]
        with self._nonces_lock:
            stored = self._nonce_store.get(nonce)
            if stored is None:
                return False
            try:
                nc = int(params["nc"], 16)
            except ValueError:
                return False
            if nc <= stored["nc"]:
                return False
            stored["nc"] = nc

        ha1 = _md5(f"{USERNAME}:{REALM}:{PASSWORD}")
        ha2 = _md5(f"{method}:{uri}")
        if params["qop"] == "auth":
            expected = _md5(
                f"{ha1}:{nonce}:{params['nc']}:{params['cnonce']}:{params['qop']}:{ha2}"
            )
        else:
            expected = _md5(f"{ha1}:{nonce}:{ha2}")
        return params["response"] == expected

    # ---- Формат частей мультипартного потока ----

    @staticmethod
    def build_part(body: bytes, lf_headers: bool = False) -> bytes:
        """Одна часть потока: разделитель + заголовки + тело (как у камеры).

        По умолчанию заголовки с CRLF (реальная камера); lf_headers=True —
        голые LF, как могут слать другие прошивки.
        """
        boundary = f"--{BOUNDARY}".encode()
        if lf_headers:
            headers = (
                b"Content-Type: text/plain\n"
                b"Content-Length: " + str(len(body)).encode() + b"\n\n"
            )
        else:
            headers = (
                b"Content-Type: text/plain\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n"
            )
        eol = b"\n" if lf_headers else b"\r\n"
        return boundary + eol + headers + body + eol

    # ---- Генерация события камеры (детерминированная копия образца) ----

    def generate_event(
        self,
        plate: str,
        country: str = "PSE",
        color: str = "Blue",
        sign: str = "Unknown",
        trust_car: bool | None = None,
    ) -> dict:
        self._event_counter += 1
        self._group_counter += 1
        self._object_counter += 1
        self._frame_seq += 1
        self._encode_seq += 1
        self._pts_counter += 1000.0
        self._real_utc_base += 30

        if trust_car is None:
            trust_car = plate in WHITE_LIST_PLATES

        now = time.time()
        utc = int(now)
        utc_ms = int((now - utc) * 1000)

        def rand_offset(base: int, delta: int) -> int:
            return self._rng.randint(base - delta, base + delta)

        comm_info = {
            "CoordinateX": None,
            "CoordinateY": None,
            "Country": country,
            "ExtraPlateNumber": None,
            "ParkType": 0,
            "Province": "Unknown",
            "Seat": [
                {
                    "PhoneConf": None,
                    "SafeBelt": "unknow",
                    "SafeBeltConf": None,
                    "SmokeConf": None,
                    "Status": ["unknow", "unknow"],
                    "Type": "Main",
                },
                {
                    "PhoneConf": None,
                    "SafeBelt": "unknow",
                    "SafeBeltConf": None,
                    "SmokeConf": None,
                    "Status": ["unknow", "unknow"],
                    "Type": "Slave",
                },
            ],
            "SnapCategory": "Motor",
            "VehicleTypeInTollStation": "Unknown",
        }

        obj = {
            "Action": "Appear",
            "BelongId": 0,
            "BoundingBox": [
                rand_offset(2000, 100),
                rand_offset(2928, 100),
                rand_offset(2768, 100),
                rand_offset(3616, 100),
            ],
            "Category": "",
            "Center": [0, 0],
            "Confidence": self._rng.randint(10, 95),
            "Country": country,
            "ExtraPlateNumber": None,
            "MainColor": [255, 255, 255, 0],
            "MainSeat": {
                "DriverCalling": "unknow",
                "DriverSmoking": "unknow",
                "SafeBelt": "unknow",
            },
            "ObjectID": self._object_counter,
            "ObjectType": "Plate",
            "OriginalBoundingBox": [
                rand_offset(656, 50),
                rand_offset(607, 50),
                rand_offset(908, 50),
                rand_offset(734, 50),
            ],
            "PlateInfo": None,
            "Province": "Unknown",
            "RecogniseConf": 0,
            "RecogniseEqualVoting": self._rng.randint(0, 1),
            "RelativeID": self._object_counter,
            "SlaveSeat": {
                "DriverCalling": "unknow",
                "DriverSmoking": "unknow",
                "SafeBelt": "unknow",
            },
            "Speed": 0,
            "Text": plate,
            "TrackType": self._rng.randint(0, 1),
            "ValidAnalyseAttributes": 0,
        }

        if trust_car:
            white_list = {
                "BeginTime": "2026-07-21 00:00:00",
                "CancelTime": "2037-12-31 23:59:59",
                "CardID": "",
                "CreateTime": 1784649022,
                "CustomParkNo": "",
                "DepartMent": " ",
                "Enable": True,
                "Location": 0,
                "MasterOfCar": "",
                "PlateColor": "",
                "PlateNumber": plate,
                "PlateType": "",
                "RecNo": 10,
                "TelephoneNumber": " ",
                "TrustCar": True,
                "VehicleColor": "",
                "VehicleType": "",
            }
        else:
            white_list = {"Enable": self._rng.choice([True, False]), "TrustCar": False}

        traffic_car = {
            "BlackList": {"Enable": False},
            "CapTime": round(utc + utc_ms / 1000.0, 3),
            "CarType": "TrustCar" if trust_car else "NormalCar",
            "Category": self._rng.choice(["SUV", "Unknown"]),
            "CountInGroup": 1,
            "Country": country,
            "CustomRoadwayDirection": "",
            "DefendCode": "".join(
                self._rng.choices(
                    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                    k=16,
                )
            ),
            "DetailedAddress": "Area-Z",
            "DeviceAddress": "",
            "Direction": 0,
            "DrivingDirection": ["Approach", "", ""],
            "Event": "TrafficJunction",
            "GroupID": self._group_counter,
            "IndexInGroup": 1,
            "Lane": 1,
            "LowerSpeedLimit": 20,
            "MachineAddress": "",
            "MachineGroup": "",
            "MachineName": "BJ09E86PAJ49B63",
            "MachineName1": "",
            "OverSpeedMargin": 0,
            "PhysicalLane": 0,
            "PlateColor": "White",
            "PlateNumber": plate,
            "PlateType": "",
            "RoadwayNo": "",
            "RouteNo": "",
            "SpeedForSize": False,
            "UTC": utc,
            "UnderSpeedMargin": 0,
            "UpperSpeedLimit": 70,
            "VehicleColor": color,
            "VehicleSign": sign,
            "VehicleSize": "Light-duty",
            "WhiteList": white_list,
        }

        main_color = [0, 0, 0, 0] if color == "Black" else [0, 0, 255, 0]
        vehicle = {
            "Action": "Appear",
            "BelongId": 0,
            "BoundingBox": [
                rand_offset(1632, 100),
                rand_offset(0, 100),
                rand_offset(6912, 100),
                rand_offset(6576, 100),
            ],
            "BrandYear": 0,
            "BrandYearText": "Другой",
            "CarLogoIndex": self._rng.randint(0, 10),
            "CarSeriesIndex": 0,
            "CarSeriesIndexYear": 0,
            "Category": self._rng.choice(["SUV", "Unknown"]),
            "Center": [rand_offset(4272, 100), rand_offset(3288, 100)],
            "Confidence": 94,
            "HeadDirection": 0,
            "MainColor": main_color,
            "MainSeat": {
                "DriverCalling": "unknow",
                "DriverSmoking": "unknow",
                "SafeBelt": "unknow",
            },
            "ObjectID": self._object_counter,
            "ObjectType": "Vehicle",
            "OriginalBoundingBox": [
                rand_offset(535, 50),
                rand_offset(64, 50),
                rand_offset(2268, 50),
                rand_offset(1284, 50),
            ],
            "RelativeID": self._object_counter,
            "SlaveSeat": {
                "DriverCalling": "unknow",
                "DriverSmoking": "unknow",
                "SafeBelt": "unknow",
            },
            "Speed": 0,
            "SubBrand": 0,
            "SubText": "Другой",
            "Text": sign,
            "ValidAnalyseAttributes": 0,
            "VehicleDirection": "Head",
            "VehicleTypeInTollStation": "Unknown",
        }
        if self._rng.random() < 0.3:
            # Иногда камера дописывает Direction в образцах — сохраняем вариативность
            vehicle["Direction"] = self._rng.choice(["Straight", "Left", "Right"])

        yuv = {
            "AddrU": 2923375616 + self._rng.randint(0, 1000000),
            "AddrV": 2924397056 + self._rng.randint(0, 1000000),
            "AddrY": 2919289856 + self._rng.randint(0, 1000000),
            "Channel": 0,
            "Format": 9,
            "FrmSeq": self._frame_seq,
            "Height": 1520,
            "PhyAddrU": 1162349568 + self._rng.randint(0, 1000000),
            "PhyAddrV": 1163371008 + self._rng.randint(0, 1000000),
            "PhyAddrY": 1158263808 + self._rng.randint(0, 1000000),
            "Priv": 2366197608 + self._rng.randint(0, 1000000),
            "SourceType": 0,
            "Stride": [2688, 1344, 1344],
            "Width": 2688,
            "YuvPts": self._pts_counter,
        }

        return {
            "Action": "Pulse",
            "Class": "Traffic",
            "Code": "TrafficJunction",
            "CommInfo": comm_info,
            "CountInGroup": 1,
            "DSTTune": 0,
            "DetectRegion": [[0, 0], [8191, 0], [8191, 8191], [0, 8191]],
            "EncodeSequence": self._encode_seq,
            "EncodeTimes": 0,
            "EventID": self._event_counter,
            "FrameSequence": self._frame_seq,
            "FrameStamp": self._frame_seq - 717,
            "GroupID": self._group_counter,
            "Index": 0,
            "IndexInGroup": 1,
            "JunctionDirection": "Obverse",
            "Lane": 0,
            "Mark": 0,
            "Name": "TrafficJunction0",
            "Object": obj,
            "ObjectID": self._object_counter,
            "OpenStrobeState": self._rng.choice(["Close", "Auto"]),
            "PTS": self._pts_counter,
            "RealUTC": self._real_utc_base,
            "RuleID": 0,
            "Sequence": 1,
            "Source": 2505343032,
            "TimeZone": 3,
            "TrafficCar": traffic_car,
            "TriggerType": 2,
            "UTC": utc,
            "UTCMS": utc_ms,
            "Vehicle": vehicle,
            "VehicleDirection": "Head",
            "VehicleHeadDirection": 0,
            "ViolationSnapSource": 3,
            "WithSnap": True,
            "YuvPacket": yuv,
        }


class _CameraHandler(http.server.BaseHTTPRequestHandler):
    """Обработчик запросов: Digest-челлендж + стрим событий.

    Протокол HTTP/1.1 с keep-alive и Transfer-Encoding: chunked — так делает
    реальная камера (в потоке кадров события передаются чанками).
    """

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        pass  # тишина в тестовых логах

    def do_GET(self) -> None:
        server: CameraEmulator = self.server.camera  # type: ignore[attr-defined]
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != ATTACH_PATH:
            self.send_error(404, "Not Found")
            return

        auth = self.headers.get("Authorization")
        if not server.authorized(auth, "GET", self.path):
            self._send_text(401, "Unauthorized", server.digest_challenge())
            return

        params = urllib.parse.parse_qs(parsed.query)
        if params.get("action") != ["attach"] or params.get("codes") != [
            "[TrafficJunction]"
        ]:
            self._send_text(400, "Invalid parameters")
            return

        self._stream_events(server)

    def _send_text(
        self, status: int, message: str, challenge: str | None = None
    ) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        if challenge:
            self.send_header("WWW-Authenticate", challenge)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    @staticmethod
    def _chunked(data: bytes) -> bytes:
        """Обрамить данные в чанк Transfer-Encoding: chunked."""
        return hex(len(data))[2:].encode() + b"\r\n" + data + b"\r\n"

    def _stream_events(self, server: CameraEmulator) -> None:
        self.send_response(200)
        self.send_header(
            "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}"
        )
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        while not server._stop_flag.is_set():
            try:
                body = server._events.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.wfile.write(
                    self._chunked(server.build_part(body, lf_headers=server.lf_headers))
                )
                self.wfile.flush()
            except OSError:
                return  # клиент закрыл соединение
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.close()
        except OSError:
            pass
