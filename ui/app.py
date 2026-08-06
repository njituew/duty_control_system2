"""Root application window."""

import logging
import queue
import sys
from datetime import datetime, timezone
from pathlib import Path
from tkinter import TclError
from typing import ClassVar

import customtkinter as ctk

from config import (
    CAMERA_EVENT_CODES,
    CAMERA_HOST,
    CAMERA_PASSWORD,
    CAMERA_QUEUE_POLL_MS,
    CAMERA_USER,
    C,
)
from database import Database, DatabaseError
from integration.camera_client import CameraListener
from ui.tabs import AccountingTab, HistoryTab, StatsTab

logger = logging.getLogger(__name__)


class App(ctk.CTk):
    """Main application window."""

    _NAV_ITEMS: ClassVar[list[tuple[str, str, str]]] = [
        ("accounting", "📋", "Учёт"),
        ("history", "🕒", "История"),
        ("stats", "📊", "Статистика"),
    ]

    def __init__(self):
        super().__init__()
        self.title("Система контроля")
        self.geometry("1500x800")
        self.minsize(900, 600)
        self.configure(fg_color=C["bg"])
        self._set_icon()

        self.db = Database()
        self._build()
        self._start_camera_listener()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Defer maximise until after the initial geometry pass;
        # winfo_screenwidth() can return 1 on some platforms if called too early.
        self.after(0, self._maximize_window)

    def _set_icon(self) -> None:
        """Set the window icon for both dev and PyInstaller frozen modes."""
        if getattr(sys, "frozen", False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent.parent
        icon_path = base / "icon.ico"
        if icon_path.exists():
            self.iconbitmap(str(icon_path))

    def _maximize_window(self) -> None:
        """Maximise the window in a cross-platform way."""
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
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=1, column=0, sticky="nsew")
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
            text="  ⬡  РАСХОД",
            font=ctk.CTkFont(family="Courier", size=14, weight="bold"),
            text_color=C["accent"],
        ).grid(row=0, column=0, padx=16, pady=14, sticky="w")

        self._clock_lbl = ctk.CTkLabel(
            header,
            text="",
            font=ctk.CTkFont(family="Courier", size=13),
            text_color=C["subtext"],
        )
        self._clock_lbl.grid(row=0, column=2, padx=16, sticky="e")
        self._tick()

    def _tick(self) -> None:
        """Update the clock label and reschedule itself every second."""
        self._clock_lbl.configure(
            text=datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y  %H:%M:%S")
        )
        self.after(1000, self._tick)

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        sidebar = ctk.CTkFrame(
            parent, fg_color=C["surface"], corner_radius=0, width=200
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        ctk.CTkFrame(sidebar, height=1, fg_color=C["border"]).pack(fill="x")

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, icon, label in self._NAV_ITEMS:
            btn = ctk.CTkButton(
                sidebar,
                text=f"  {icon}  {label}",
                font=ctk.CTkFont(size=13),
                anchor="w",
                fg_color="transparent",
                hover_color=C["card"],
                text_color=C["subtext"],
                height=46,
                corner_radius=0,
                command=lambda k=key: self._show_tab(k),
            )
            btn.pack(fill="x", padx=0, pady=1)
            self._nav_buttons[key] = btn

        ctk.CTkFrame(sidebar, height=1, fg_color=C["border"]).pack(
            fill="x", side="bottom"
        )
        ctk.CTkLabel(
            sidebar,
            text="v2.0",
            font=ctk.CTkFont(size=10),
            text_color=C["subtext"],
        ).pack(side="bottom", pady=8)

    def _build_content(self, parent: ctk.CTkFrame) -> None:
        """Stack all tab frames in the same grid cell; tkraise() switches between them."""
        content = ctk.CTkFrame(parent, fg_color=C["bg"])
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._tabs: dict[str, ctk.CTkFrame] = {
            "accounting": AccountingTab(content, self.db),
            "history": HistoryTab(content, self.db),
            "stats": StatsTab(content, self.db),
        }

        for tab in self._tabs.values():
            tab.grid(row=0, column=0, sticky="nsew")

    def _show_tab(self, key: str) -> None:
        self._tabs[key].tkraise()

        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(fg_color=C["card"], text_color=C["accent"])
            else:
                btn.configure(fg_color="transparent", text_color=C["subtext"])

        # History and stats tabs are refreshed on every visit to avoid stale data.
        if key in ("history", "stats"):
            self._tabs[key].refresh()

    def _start_camera_listener(self) -> None:
        """Start the camera listener thread and begin polling its event queue."""
        if not CAMERA_HOST:
            logger.info("Camera integration is disabled")
            return
        self._camera_queue: queue.Queue[str] = queue.Queue()
        self._camera_listener = CameraListener(
            host=CAMERA_HOST,
            user=CAMERA_USER,
            password=CAMERA_PASSWORD,
            codes=CAMERA_EVENT_CODES,
            event_queue=self._camera_queue,
        )
        self._camera_listener.start()
        logger.info("Camera listener started on %s", CAMERA_HOST)
        self.after(CAMERA_QUEUE_POLL_MS, self._poll_camera_queue)

    def _poll_camera_queue(self) -> None:
        """Drain recognised plate numbers and toggle matching vehicles' status."""
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
        if hasattr(self, "_camera_listener"):
            self._camera_listener.stop()
        self.destroy()
