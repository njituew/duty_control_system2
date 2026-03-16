"""Root application window."""

import sys
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

from config import C
from database import Database
from ui.tabs import EntityTab, HistoryTab, StatsTab


class App(ctk.CTk):
    """Main window of the duty control application."""

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
        self._set_icon()

        self.db = Database()
        self._build()
        self.after(0, self._maximize_window)

    def _set_icon(self) -> None:
        """Set the window icon, resolving the path for both dev and frozen modes."""
        if getattr(sys, "frozen", False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent.parent
        icon_path = base / "icon.ico"
        if icon_path.exists():
            self.iconbitmap(str(icon_path))

    def _maximize_window(self) -> None:
        """Expand the window to fill the screen in a cross-platform way."""
        import sys

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
            except Exception:
                w = self.winfo_screenwidth()
                h = self.winfo_screenheight()
                self.geometry(f"{w}x{h}+0+0")

    def _build(self) -> None:
        """Assemble the top-level layout: header, sidebar, and content area."""
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

    def _build_header(self) -> None:
        """Build the top header bar with the app title and live clock."""
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
        """Update the clock label every second."""
        self._clock_lbl.configure(text=datetime.now().strftime("%d.%m.%Y  %H:%M:%S"))
        self.after(1000, self._tick)

    def _build_sidebar(self, parent: ctk.CTkFrame) -> None:
        """Build the left navigation sidebar."""
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
        """Create all tab frames stacked on top of each other."""
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

    def _show_tab(self, key: str) -> None:
        """Raise the selected tab and update the sidebar button states.

        Args:
            key: Tab identifier — one of 'vehicles', 'commanders',
                'history', 'stats'.
        """
        self._tabs[key].tkraise()

        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(fg_color=C["card"], text_color=C["accent"])
            else:
                btn.configure(fg_color="transparent", text_color=C["subtext"])

        # History and stats always show fresh data when switched to.
        if key in ("history", "stats"):
            self._tabs[key].refresh()
