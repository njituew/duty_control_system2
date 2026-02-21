"""Вкладки: EntityTab, HistoryTab, StatsTab."""

import customtkinter as ctk
from tkinter import messagebox

from config import C, EVENT_LABELS, EVENT_COLORS, STATUS_MAP, TYPE_LABELS
from database import Database
from ui.components import EntityCard, ScrollableCardFrame
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

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build(title, search_placeholder)
        self.refresh()

    def _build(self, title: str, search_placeholder: str):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=C["text"],
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            header,
            text="＋  Добавить",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C["accent"],
            hover_color=C["accent_h"],
            corner_radius=8,
            height=36,
            command=self._on_add,
        ).grid(row=0, column=1, sticky="e")

        self._counter_lbl = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11), text_color=C["subtext"]
        )
        self._counter_lbl.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 4))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self.refresh())
        ctk.CTkEntry(
            self,
            textvariable=self._search_var,
            placeholder_text=f"🔍  {search_placeholder}",
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"],
            border_color=C["border"],
            height=36,
            corner_radius=8,
        ).grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))

        self._cards_frame = ScrollableCardFrame(self)
        self._cards_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def refresh(self):
        self._cards_frame.clear()
        query = self._search_var.get().strip()

        if self.entity_type == "vehicle":
            rows = self.db.get_vehicles(query)
        else:
            rows = self.db.get_commanders(query)

        self._counter_lbl.configure(text=f"Записей: {len(rows)}")

        for row in rows:
            card = EntityCard(
                self._cards_frame,
                self.db,
                self.entity_type,
                row,
                on_delete=self._on_delete_card,
            )
            self._cards_frame.add_card(card)

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

    def _on_delete_card(self, card: EntityCard):
        if not messagebox.askyesno("Удаление", f"Удалить «{card.ename}»?", parent=self):
            return
        if self.entity_type == "vehicle":
            self.db.delete_vehicle(card.eid)
        else:
            self.db.delete_commander(card.eid)
        self.refresh()


class HistoryTab(ctk.CTkFrame):
    """Вкладка истории событий."""

    _TABLE_HEADERS = ["Время", "Тип", "Наименование", "Событие"]

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

        self._table = ctk.CTkScrollableFrame(
            self, fg_color=C["surface"], corner_radius=10
        )
        self._table.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._table.grid_columnconfigure((0, 1, 2, 3), weight=1)

        for col, text in enumerate(self._TABLE_HEADERS):
            ctk.CTkLabel(
                self._table,
                text=text,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=C["accent"],
            ).grid(row=0, column=col, sticky="w", padx=12, pady=(8, 4))

        ctk.CTkFrame(self._table, height=1, fg_color=C["border"]).grid(
            row=1, column=0, columnspan=4, sticky="ew", padx=8, pady=2
        )

    def refresh(self):
        for widget in self._table.winfo_children():
            info = widget.grid_info()
            if info and int(info["row"]) > 1:
                widget.destroy()

        events = self.db.get_events(self._search_var.get().strip())

        for i, ev in enumerate(events):
            row = i + 2
            color = EVENT_COLORS.get(ev["event_type"], C["text"])
            cells = [
                ev["ts"],
                TYPE_LABELS.get(ev["entity_type"], ev["entity_type"]),
                ev["entity_name"],
                EVENT_LABELS.get(ev["event_type"], ev["event_type"]),
            ]
            for col, value in enumerate(cells):
                ctk.CTkLabel(
                    self._table,
                    text=value,
                    font=ctk.CTkFont(size=11),
                    text_color=color if col == 3 else C["text"],
                    anchor="w",
                ).grid(row=row, column=col, sticky="w", padx=12, pady=2)

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
            ("ТС в базе", str(s["vehicles"]), C["accent"]),
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
