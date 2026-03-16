"""Application tabs: EntityTab, HistoryTab, StatsTab."""

import customtkinter as ctk
from tkinter import messagebox

from config import C
from database import Database, DatabaseError, DuplicateError
from ui.components import EntityTable, EventTreeview
from ui.dialogs import InputDialog


class EntityTab(ctk.CTkFrame):
    """Tab that displays and manages a list of vehicles or commanders."""

    def __init__(
        self,
        master,
        db: Database,
        entity_type: str,
        title: str,
        add_prompt: str,
        search_placeholder: str,
        **kwargs,
    ):
        super().__init__(master, fg_color=C["bg"], **kwargs)
        self.db = db
        self.entity_type = entity_type
        self.add_prompt = add_prompt

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build(title, search_placeholder)
        self.refresh()

    def _build(self, title: str, search_placeholder: str) -> None:
        self._build_toolbar(title, search_placeholder)
        self._build_hints()

        self._table = EntityTable(
            self,
            self.db,
            self.entity_type,
            on_changed=self._on_table_changed,
        )
        self._table.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _build_toolbar(self, title: str, search_placeholder: str) -> None:
        """Build the title label, search box, and add button."""
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        toolbar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            toolbar,
            text=title,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=C["text"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))

        search_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        search_frame.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        search_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            search_frame,
            text="Поиск",
            font=ctk.CTkFont(size=12),
            text_color=C["subtext"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self.refresh())
        ctk.CTkEntry(
            search_frame,
            textvariable=self._search_var,
            placeholder_text=f"🔍  {search_placeholder}",
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"],
            border_color=C["border"],
            height=34,
            corner_radius=8,
        ).grid(row=0, column=1, sticky="ew")

        ctk.CTkButton(
            toolbar,
            text="＋  Добавить",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C["accent"],
            hover_color=C["accent_h"],
            corner_radius=8,
            height=34,
            command=self._on_add,
        ).grid(row=0, column=2, sticky="e")

    def _build_hints(self) -> None:
        """Build the row counter and keyboard-hint labels."""
        hints = ctk.CTkFrame(self, fg_color="transparent")
        hints.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 6))
        hints.grid_columnconfigure(0, weight=1)

        self._counter_lbl = ctk.CTkLabel(
            hints, text="", font=ctk.CTkFont(size=11), text_color=C["subtext"]
        )
        self._counter_lbl.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            hints,
            text="Нажатие по строке — прибыл / убыл   ·   нажатие по 🗑 — удалить запись",
            font=ctk.CTkFont(size=10),
            text_color=C["subtext"],
        ).grid(row=0, column=1, sticky="e")

    def refresh(self) -> None:
        """Reload the table from the database using the current search query."""
        query = self._search_var.get().strip()
        rows = (
            self.db.get_vehicles(query)
            if self.entity_type == "vehicle"
            else self.db.get_commanders(query)
        )
        self._table.populate(rows)
        self._update_counter()

    def _on_table_changed(self) -> None:
        self._update_counter()

    def _update_counter(self) -> None:
        self._counter_lbl.configure(text=f"Записей: {self._table.row_count()}")

    def _on_add(self) -> None:
        """Open the input dialog and insert the new entity if confirmed."""
        dialog = InputDialog(self, title="Добавить", prompt=self.add_prompt)
        text = dialog.get_input()
        if text is None:
            return

        try:
            (
                self.db.add_vehicle(text)
                if self.entity_type == "vehicle"
                else self.db.add_commander(text)
            )
            self.refresh()
        except DuplicateError:
            messagebox.showwarning("Дубликат", f"«{text}» уже существует.", parent=self)
        except (DatabaseError, ValueError) as e:
            messagebox.showerror("Ошибка", str(e), parent=self)


class HistoryTab(ctk.CTkFrame):
    """Tab that shows the full event log with search and clear controls."""

    def __init__(self, master, db: Database, **kwargs):
        super().__init__(master, fg_color=C["bg"], **kwargs)
        self.db = db
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build()
        self.refresh()

    def _build(self) -> None:
        self._build_header()
        self._build_search()

        self._tree_widget = EventTreeview(
            self, heading_color=C["accent"], row_height=28
        )
        self._tree_widget.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _build_header(self) -> None:
        """Build the title and the refresh/clear action buttons."""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="История событий",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=C["text"],
        ).grid(row=0, column=0, sticky="w")

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(
            btn_frame,
            text="↻  Обновить",
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"],
            hover_color=C["border"],
            text_color=C["text"],
            corner_radius=8,
            height=34,
            command=self.refresh,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="🗑  Очистить",
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"],
            hover_color="#2a1a1a",
            text_color=C["red"],
            corner_radius=8,
            height=34,
            command=self._on_clear,
        ).pack(side="left")

    def _build_search(self) -> None:
        """Build the search entry that filters events in real time."""
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self.refresh())
        ctk.CTkEntry(
            self,
            textvariable=self._search_var,
            placeholder_text="🔍  Поиск по имени или событию...",
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"],
            border_color=C["border"],
            height=36,
            corner_radius=8,
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

    def refresh(self) -> None:
        """Reload events from the database using the current search query."""
        events = self.db.get_events(self._search_var.get().strip())
        self._tree_widget.populate(events)

    def _on_clear(self) -> None:
        """Ask for confirmation, then delete all event history."""
        if messagebox.askyesno(
            "Очистить историю", "Удалить всю историю событий?", parent=self
        ):
            try:
                self.db.clear_events()
            except DatabaseError as e:
                messagebox.showerror("Ошибка", str(e), parent=self)
            self.refresh()


class StatsTab(ctk.CTkFrame):
    """Tab that shows aggregate statistics and a recent-activity feed."""

    _STAT_CARDS = [
        ("ТС", "vehicles", "accent"),
        ("Командиров", "commanders", "green"),
        ("Прибытий", "arrivals", "green"),
        ("Убытий", "departures", "red"),
        ("Всего событий", "total_events", "yellow"),
    ]

    def __init__(self, master, db: Database, **kwargs):
        super().__init__(master, fg_color=C["bg"], **kwargs)
        self.db = db
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build()
        self.refresh()

    def _build(self) -> None:
        self._build_header()

        self._stats_row = ctk.CTkFrame(self, fg_color="transparent")
        self._stats_row.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))

        recent_panel = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=10)
        recent_panel.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        recent_panel.grid_rowconfigure(2, weight=1)
        recent_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            recent_panel,
            text="Последние события",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 6))

        ctk.CTkFrame(recent_panel, height=1, fg_color=C["border"]).grid(
            row=1, column=0, sticky="ew", padx=12, pady=(0, 6)
        )

        self._recent_tree = EventTreeview(
            recent_panel, heading_color=C["accent"], row_height=28
        )
        self._recent_tree.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _build_header(self) -> None:
        """Build the title and refresh button."""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Статистика",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=C["text"],
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            header,
            text="↻  Обновить",
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"],
            hover_color=C["border"],
            text_color=C["text"],
            corner_radius=8,
            height=34,
            command=self.refresh,
        ).grid(row=0, column=1, sticky="e")

    def _make_stat_card(
        self, parent, col: int, title: str, value: str, color: str
    ) -> None:
        """Create a single numbered stat card inside the stats row.

        Args:
            parent: The container frame.
            col: Grid column index.
            title: Label shown below the number.
            value: Large number to display.
            color: Hex color for the number text.
        """
        frame = ctk.CTkFrame(
            parent,
            fg_color=C["card"],
            corner_radius=10,
            border_width=1,
            border_color=C["border"],
        )
        frame.grid(row=0, column=col, padx=6, pady=4, sticky="ew")
        parent.grid_columnconfigure(col, weight=1)

        ctk.CTkLabel(
            frame,
            text=value,
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color=color,
        ).pack(pady=(16, 2))

        ctk.CTkLabel(
            frame, text=title, font=ctk.CTkFont(size=11), text_color=C["subtext"]
        ).pack(pady=(0, 14))

    def refresh(self) -> None:
        """Rebuild stat cards and reload the recent-activity list."""
        for widget in self._stats_row.winfo_children():
            widget.destroy()

        stats = self.db.stats()
        for i, (title, key, color_key) in enumerate(self._STAT_CARDS):
            self._make_stat_card(
                self._stats_row, i, title, str(stats[key]), C[color_key]
            )

        recent = self.db.recent_activity(10)
        self._recent_tree.populate(recent)
