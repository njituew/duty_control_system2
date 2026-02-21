"""Главное окно приложения."""

from datetime import datetime

import customtkinter as ctk

from config import C
from database import Database
from ui.tabs import EntityTab, HistoryTab, StatsTab


class App(ctk.CTk):
    """Корневое окно приложения."""

    _NAV_ITEMS = [
        ("vehicles", "🚗", "ТС"),
        ("commanders", "👤", "Командование"),
        ("history", "📋", "История"),
        ("stats", "📊", "Статистика"),
    ]

    def __init__(self):
        super().__init__()
        self.title("Система контроля")
        self.geometry("1500x800")
        self.minsize(900, 600)
        self.configure(fg_color=C["bg"])

        self.db = Database()
        self._build()
        self._maximize_window()

    def _maximize_window(self):
        """Разворачивает окно на весь экран."""
        self.update_idletasks()
        self.state("zoomed")

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=1, column=0, sticky="nsew")
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)

        self._build_sidebar(main)
        self._build_content(main)
        self._show_tab("vehicles")

    def _build_header(self):
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

    def _tick(self):
        self._clock_lbl.configure(text=datetime.now().strftime("%d.%m.%Y  %H:%M:%S"))
        self.after(1000, self._tick)

    def _build_sidebar(self, parent):
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

    def _build_content(self, parent):
        content = ctk.CTkFrame(parent, fg_color=C["bg"])
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._tabs: dict[str, ctk.CTkFrame] = {
            "vehicles": EntityTab(
                content,
                self.db,
                entity_type="vehicle",
                title="Транспортные средства",
                add_prompt="Введите номер ТС:",
                search_placeholder="Поиск по номеру ТС...",
            ),
            "commanders": EntityTab(
                content,
                self.db,
                entity_type="commander",
                title="Командование",
                add_prompt="Введите ФИО командира:",
                search_placeholder="Поиск по ФИО...",
            ),
            "history": HistoryTab(content, self.db),
            "stats": StatsTab(content, self.db),
        }

        for tab in self._tabs.values():
            tab.grid(row=0, column=0, sticky="nsew")

    def _show_tab(self, key: str):
        self._tabs[key].tkraise()

        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(fg_color=C["card"], text_color=C["accent"])
            else:
                btn.configure(fg_color="transparent", text_color=C["subtext"])

        if key in ("history", "stats"):
            self._tabs[key].refresh()
