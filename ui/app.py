"""Главное окно приложения."""

import logging
import queue
import sys
from datetime import datetime, timezone
from pathlib import Path
from tkinter import TclError
from typing import ClassVar

import customtkinter as ctk

from camera.camera_client import CameraListener
from core.camera_settings import load_settings, save_settings
from core.config import CAMERA_EVENT_CODES, CAMERA_QUEUE_POLL_MS, C
from core.database import Database, DatabaseError
from ui.tabs import AccountingTab, HistoryTab, SettingsTab, StatsTab

logger = logging.getLogger(__name__)


class App(ctk.CTk):
    """Главное окно: навигация, вкладки и интеграция с камерой."""

    _NAV_ITEMS: ClassVar[list[tuple[str, str, str]]] = [
        ("accounting", "▤", "Учёт"),
        ("history", "≡", "История"),
        ("stats", "◆", "Статистика"),
        ("settings", "⚙", "Настройки"),
    ]

    def __init__(self, db: Database | None = None):
        super().__init__()
        self.title("Система контроля")
        self.geometry("1500x800")
        self.minsize(900, 600)
        self.configure(fg_color=C["bg"])
        self._set_icon()

        self.db = db or Database()
        self._camera_listener = None
        self._camera_host = ""
        self._camera_state = ""
        self._camera_polling = False

        self._camera_banner = None

        self._build()
        self._auto_connect_camera()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Откладываем разворот окна: winfo_screenwidth() может вернуть 1
        # слишком рано.
        self.after(0, self._maximize_window)

    def _set_icon(self) -> None:
        """Установить иконку окна для разработки и PyInstaller-сборки."""
        if getattr(sys, "frozen", False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent.parent
        icon_path = base / "icon.ico"
        if icon_path.exists():
            self.iconbitmap(str(icon_path))

    def _maximize_window(self) -> None:
        """Развернуть окно на весь экран кросс-платформенным способом."""
        self.update_idletasks()
        if sys.platform == "win32":
            self.state("zoomed")
        elif sys.platform == "darwin":
            w = self.winfo_screenwidth()
            h = self.winfo_screenheight()
            self.geometry(f"{w}x{h}+0+0")
        else:
            try:
                self.state("zoomed")
            except TclError:
                w = self.winfo_screenwidth()
                h = self.winfo_screenheight()
                self.geometry(f"{w}x{h}+0+0")

    def _build(self) -> None:
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_camera_banner()

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=2, column=0, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)

        self._build_sidebar(main)
        self._build_content(main)
        self._show_tab("accounting")

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=0, height=54)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        header.grid_propagate(False)

        ctk.CTkLabel(
            header,
            text="РАСХОД",
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            text_color=C["accent"],
        ).grid(row=0, column=0, padx=18, pady=15, sticky="w")

        # Статусбар камеры: зелёный «подключено», жёлтый «разорвано», пусто — иначе.
        self._camera_status_lbl = ctk.CTkLabel(
            header, text="", font=ctk.CTkFont(size=12, weight="bold")
        )
        self._camera_status_lbl.grid(row=0, column=1, sticky="e", padx=16)

        self._clock_lbl = ctk.CTkLabel(
            header,
            text="",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=C["subtext"],
        )
        self._clock_lbl.grid(row=0, column=2, padx=18, sticky="e")
        self._tick()

    def _build_camera_banner(self) -> None:
        """Заметная плашка об обрыве связи с камерой; скрыта по умолчанию."""
        self._camera_banner = ctk.CTkFrame(
            self, fg_color=C["danger_h"], corner_radius=0, height=38
        )
        self._camera_banner.grid(row=1, column=0, sticky="ew")
        self._camera_banner.grid_propagate(False)
        self._camera_banner.grid_remove()

        ctk.CTkLabel(
            self._camera_banner,
            text="⚠  Соединение с камерой разорвано. Автоматический учёт не работает. Регистрируйте события вручную",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["yellow"],
        ).pack(pady=9, padx=16, anchor="w")

    def _update_camera_banners(self) -> None:
        """Обновить статусбар в шапке и баннер обрыва по состоянию камеры."""
        state = self._camera_state
        if state == "connected":
            self._camera_status_lbl.configure(
                text="Камера подключена", text_color=C["green"]
            )
            self._camera_banner.grid_remove()
        elif state == "error":
            self._camera_status_lbl.configure(
                text="Соединение с камерой разорвано. События не регистрируются автоматически",
                text_color=C["yellow"],
            )
            self._camera_banner.grid()
        else:
            self._camera_status_lbl.configure(text="")
            self._camera_banner.grid_remove()

    def _tick(self) -> None:
        """Обновить часы и перепланировать себя каждую секунду."""
        self._clock_lbl.configure(
            text=datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y  %H:%M:%S")
        )
        self.after(1000, self._tick)

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        sidebar = ctk.CTkFrame(
            parent, fg_color=C["surface"], corner_radius=0, width=196
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        self._nav_indicators: dict[str, ctk.CTkLabel] = {}
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, _icon, label in self._NAV_ITEMS:
            row = ctk.CTkFrame(sidebar, fg_color="transparent")
            row.pack(fill="x")
            row.grid_columnconfigure(0, weight=0)
            row.grid_columnconfigure(1, weight=1)

            indicator = ctk.CTkLabel(
                row, text="", width=3, height=18, fg_color=C["accent"], corner_radius=0
            )
            indicator.grid(row=0, column=0, padx=(0, 4))

            btn = ctk.CTkButton(
                row,
                text=label,
                font=ctk.CTkFont(size=13),
                anchor="w",
                fg_color="transparent",
                hover_color=C["card"],
                text_color=C["subtext"],
                height=42,
                corner_radius=0,
                command=lambda k=key: self._show_tab(k),
            )
            btn.grid(row=0, column=1, sticky="ew", padx=(0, 8))
            self._nav_indicators[key] = indicator
            self._nav_buttons[key] = btn

    def _build_content(self, parent: ctk.CTkFrame) -> None:
        """Сложить все вкладки в одну ячейку; переключает их _show_tab()."""
        content = ctk.CTkFrame(parent, fg_color=C["bg"])
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._tabs: dict[str, ctk.CTkFrame] = {
            "accounting": AccountingTab(content, self.db),
            "history": HistoryTab(content, self.db),
            "stats": StatsTab(content, self.db),
            "settings": SettingsTab(content, self),
        }

        for key, tab in self._tabs.items():
            tab.grid(row=0, column=0, sticky="nsew")
            if key != "accounting":
                tab.grid_remove()

    def _show_tab(self, key: str) -> None:
        for k, tab in self._tabs.items():
            if k == key:
                tab.grid(row=0, column=0, sticky="nsew")
            else:
                tab.grid_remove()

        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(fg_color=C["card"], text_color=C["accent"])
                self._nav_indicators[k].grid()  # show
            else:
                btn.configure(fg_color="transparent", text_color=C["subtext"])
                self._nav_indicators[k].grid_remove()  # hide

        # Вкладки истории, статистики и настроек обновляются при каждом открытии.
        if key in ("history", "stats", "settings"):
            self._tabs[key].refresh()

    def _auto_connect_camera(self) -> None:
        """Восстановить последнее подключение к камере из сохранённых настроек."""
        saved = load_settings()
        if saved.get("host"):
            logger.info("Auto-connecting to camera from saved settings")
            self.connect_camera(saved["host"], saved["user"], saved["password"])

    def connect_camera(self, host: str, user: str, password: str) -> bool:
        """Сохранить учётные данные и запустить слушатель камеры.

        Возвращает False при пустом host; иначе запускает слушатель и возвращает True.
        """
        host = host.strip().rstrip("/")
        if not host:
            return False
        try:
            save_settings(host, user.strip(), password)
        except RuntimeError as exc:
            logger.warning("%s", exc)
        self._start_camera_listener(host, user.strip(), password)
        return True

    def disconnect_camera(self) -> None:
        """Остановить активный поток слушателя камеры и опрос."""
        self._stop_camera_listener()

    def _start_camera_listener(self, host: str, user: str, password: str) -> None:
        """Запустить поток слушателя камеры и начать опрос его очередей."""
        self._stop_camera_listener()
        self._camera_queue: queue.Queue[str] = queue.Queue()
        self._camera_status_queue: queue.Queue[str] = queue.Queue()
        self._camera_host = host
        self._camera_state = "connecting"
        self._camera_listener = CameraListener(
            host=host,
            user=user,
            password=password,
            codes=CAMERA_EVENT_CODES,
            event_queue=self._camera_queue,
            status_queue=self._camera_status_queue,
        )
        self._camera_listener.start()
        logger.info("Camera listener started on %s", host)
        self._tabs["settings"].update_status()
        self._update_camera_banners()
        if not self._camera_polling:
            self.after(CAMERA_QUEUE_POLL_MS, self._poll_camera_queue)
            self._camera_polling = True

    def _stop_camera_listener(self) -> None:
        """Остановить поток слушателя камеры, если он запущен."""
        if getattr(self, "_camera_listener", None) is not None:
            self._camera_listener.stop()
            self._camera_listener = None
            logger.info("Camera listener stopped")
        self._camera_host = ""
        self._camera_state = ""
        self._tabs["settings"].update_status()
        self._update_camera_banners()

    def _drain_camera_status(self) -> None:
        """Перенести статусы из потока камеры в состояние приложения."""
        status_queue = getattr(self, "_camera_status_queue", None)
        if status_queue is None:
            return
        changed = False
        try:
            while True:
                status = status_queue.get_nowait()
                if status in ("connected", "error", "connecting"):
                    self._camera_state = status
                    changed = True
        except queue.Empty:
            pass
        if changed:
            self._tabs["settings"].update_status()
            self._update_camera_banners()

    def _poll_camera_queue(self) -> None:
        """Забрать распознанные номера и переключить статус подходящих ТС."""
        if getattr(self, "_camera_listener", None) is None:
            self._camera_polling = False
            return
        self._drain_camera_status()
        changed = False
        while True:
            try:
                number = self._camera_queue.get_nowait()
            except queue.Empty:
                break
            logger.info("Processing camera event for number=%s", number)
            try:
                vehicle = self.db.toggle_vehicle_status_by_number(number)
            except DatabaseError:
                logger.exception("Failed to update vehicle status from camera event")
                continue
            if vehicle is not None:
                changed = True
                logger.info(
                    "Vehicle %s status updated to %s",
                    number,
                    vehicle["status"],
                )
            else:
                logger.info(
                    "Camera saw plate %s, no matching vehicle in database", number
                )

        if changed:
            self._tabs["accounting"].refresh()

        self.after(CAMERA_QUEUE_POLL_MS, self._poll_camera_queue)

    def _on_close(self) -> None:
        self._stop_camera_listener()
        self.destroy()
