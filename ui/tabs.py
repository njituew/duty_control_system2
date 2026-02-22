"""Вкладки: EntityTab, HistoryTab, StatsTab."""

import tkinter as tk
import tkinter.ttk as ttk
import customtkinter as ctk
from tkinter import messagebox

from config import C, EVENT_LABELS, EVENT_COLORS, STATUS_MAP, TYPE_LABELS
from database import Database
from ui.components import EntityTable
from ui.dialogs import InputDialog


class EntityTab(ctk.CTkFrame):
    """Вкладка списка ТС или командиров."""

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

    def _build(self, title: str, search_placeholder: str):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=C["text"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self.refresh())
        ctk.CTkEntry(
            header,
            textvariable=self._search_var,
            placeholder_text=f"🔍  {search_placeholder}",
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"],
            border_color=C["border"],
            height=34,
            corner_radius=8,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 12))

        ctk.CTkButton(
            header,
            text="＋  Добавить",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C["accent"],
            hover_color=C["accent_h"],
            corner_radius=8,
            height=34,
            command=self._on_add,
        ).grid(row=0, column=2, sticky="e")

        hint_frame = ctk.CTkFrame(self, fg_color="transparent")
        hint_frame.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 6))
        hint_frame.grid_columnconfigure(0, weight=1)

        self._counter_lbl = ctk.CTkLabel(
            hint_frame, text="", font=ctk.CTkFont(size=11), text_color=C["subtext"]
        )
        self._counter_lbl.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            hint_frame,
            text="Нажатие по строке — прибыл / убыл   ·   нажатие по 🗑 — удалить запись",
            font=ctk.CTkFont(size=10),
            text_color=C["subtext"],
        ).grid(row=0, column=1, sticky="e")

        self._table = EntityTable(
            self,
            self.db,
            self.entity_type,
            on_changed=self._on_table_changed,
        )
        self._table.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def refresh(self):
        query = self._search_var.get().strip()
        rows = (
            self.db.get_vehicles(query)
            if self.entity_type == "vehicle"
            else self.db.get_commanders(query)
        )
        self._table.populate(rows)
        self._counter_lbl.configure(text=f"Записей: {self._table.row_count()}")

    def _on_table_changed(self):
        self._counter_lbl.configure(text=f"Записей: {self._table.row_count()}")

    def _on_add(self):
        dialog = InputDialog(self, title="Добавить", prompt=self.add_prompt)
        text = dialog.get_input()
        if not text:
            return

        if self.entity_type == "vehicle":
            result = self.db.add_vehicle(text)
        else:
            result = self.db.add_commander(text)

        if result is None:
            messagebox.showwarning("Дубликат", f"«{text}» уже существует.", parent=self)
        else:
            self.refresh()


class HistoryTab(ctk.CTkFrame):
    """Вкладка истории событий (ttk.Treeview)."""

    _COLUMNS = ("ts", "type", "name", "event")
    _COL_HEADERS = {
        "ts": "Время",
        "type": "Тип",
        "name": "Наименование",
        "event": "Событие",
    }
    _COL_WIDTHS = {"ts": 160, "type": 100, "name": 260, "event": 120}

    def __init__(self, master, db: Database, **kwargs):
        super().__init__(master, fg_color=C["bg"], **kwargs)
        self.db = db
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build()
        self.refresh()

    def _build(self):
        self._build_header()
        self._build_search()
        self._build_tree()

    def _build_header(self):
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

    def _build_search(self):
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

    def _build_tree(self):
        """Создаёт ttk.Treeview со стилями под тёмную тему."""
        container = tk.Frame(self, bg=C["surface"], bd=0, highlightthickness=0)
        container.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "History.Treeview",
            background=C["surface"],
            foreground=C["text"],
            fieldbackground=C["surface"],
            borderwidth=0,
            rowheight=28,
            font=("Segoe UI", 10),
        )
        style.configure(
            "History.Treeview.Heading",
            background=C["card"],
            foreground=C["accent"],
            borderwidth=0,
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "History.Treeview",
            background=[("selected", C["card"])],
            foreground=[("selected", C["text"])],
        )
        style.map("History.Treeview.Heading", relief=[("active", "flat")])
        style.configure(
            "History.Vertical.TScrollbar",
            background=C["border"],
            troughcolor=C["surface"],
            arrowcolor=C["subtext"],
            borderwidth=0,
        )

        self._tree = ttk.Treeview(
            container,
            columns=self._COLUMNS,
            show="headings",
            style="History.Treeview",
            selectmode="browse",
        )

        for col in self._COLUMNS:
            self._tree.heading(col, text=self._COL_HEADERS[col])
            self._tree.column(col, width=self._COL_WIDTHS[col], minwidth=60, anchor="w")

        for event_type, color in EVENT_COLORS.items():
            self._tree.tag_configure(event_type, foreground=color)
        self._tree.tag_configure("default", foreground=C["text"])

        vsb = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self._tree.yview,
            style="History.Vertical.TScrollbar",
        )
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

    def refresh(self):
        self._tree.delete(*self._tree.get_children())

        events = self.db.get_events(self._search_var.get().strip())

        for ev in events:
            tag = ev["event_type"] if ev["event_type"] in EVENT_COLORS else "default"
            self._tree.insert(
                "",
                "end",
                values=(
                    ev["ts"],
                    TYPE_LABELS.get(ev["entity_type"], ev["entity_type"]),
                    ev["entity_name"],
                    EVENT_LABELS.get(ev["event_type"], ev["event_type"]),
                ),
                tags=(tag,),
            )

    def _on_clear(self):
        if messagebox.askyesno(
            "Очистить историю", "Удалить всю историю событий?", parent=self
        ):
            self.db.clear_events()
            self.refresh()


class StatsTab(ctk.CTkFrame):
    """Вкладка статистики."""

    def __init__(self, master, db: Database, **kwargs):
        super().__init__(master, fg_color=C["bg"], **kwargs)
        self.db = db
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build()
        self.refresh()

    def _build(self):
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

        self._stats_row = ctk.CTkFrame(self, fg_color="transparent")
        self._stats_row.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))

        self._recent_frame = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=10)
        self._recent_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._recent_frame.grid_columnconfigure(0, weight=1)

    def _make_stat_card(self, parent, col: int, title: str, value: str, color: str):
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

    def refresh(self):
        for widget in self._stats_row.winfo_children():
            widget.destroy()
        for widget in self._recent_frame.winfo_children():
            widget.destroy()

        s = self.db.stats()
        cards_data = [
            ("ТС", str(s["vehicles"]), C["accent"]),
            ("Командиров", str(s["commanders"]), C["green"]),
            ("Прибытий", str(s["arrivals"]), C["green"]),
            ("Убытий", str(s["departures"]), C["red"]),
            ("Всего событий", str(s["total_events"]), C["yellow"]),
        ]
        for i, (title, value, color) in enumerate(cards_data):
            self._make_stat_card(self._stats_row, i, title, value, color)

        ctk.CTkLabel(
            self._recent_frame,
            text="Последние события",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
        ).pack(anchor="w", padx=16, pady=(12, 6))

        ctk.CTkFrame(self._recent_frame, height=1, fg_color=C["border"]).pack(
            fill="x", padx=12, pady=(0, 6)
        )

        recent = self.db.recent_activity(10)
        if not recent:
            ctk.CTkLabel(
                self._recent_frame,
                text="Нет активности",
                font=ctk.CTkFont(size=12),
                text_color=C["subtext"],
            ).pack(pady=20)
            return

        for ev in recent:
            color = EVENT_COLORS.get(ev["event_type"], C["text"])
            icon = STATUS_MAP.get(ev["event_type"], ("◆", C["text"], "?"))[0]

            row_frame = ctk.CTkFrame(self._recent_frame, fg_color="transparent")
            row_frame.pack(fill="x", padx=16, pady=2)
            row_frame.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                row_frame, text=f"  {icon}", text_color=color, font=ctk.CTkFont(size=14)
            ).grid(row=0, column=0, padx=(0, 8))

            ctk.CTkLabel(
                row_frame,
                text=f"{ev['entity_name']}  —  {EVENT_LABELS.get(ev['event_type'], ev['event_type'])}",
                text_color=C["text"],
                font=ctk.CTkFont(size=12),
                anchor="w",
            ).grid(row=0, column=1, sticky="w")

            ctk.CTkLabel(
                row_frame,
                text=ev["ts"][11:19],
                text_color=C["subtext"],
                font=ctk.CTkFont(size=11),
            ).grid(row=0, column=2, padx=8)
