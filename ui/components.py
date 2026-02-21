"""UI-компоненты: EntityCard, ScrollableCardFrame."""

from datetime import datetime

import customtkinter as ctk

from config import C, STATUS_MAP, STATUS_ORDER
from database import Database


class EntityCard(ctk.CTkFrame):
    """Карточка ТС или командира. Клик меняет статус: idle → arrived → departed."""

    def __init__(
        self,
        master,
        db: Database,
        entity_type: str,
        row_data,
        on_delete,
        **kwargs,
    ):
        super().__init__(
            master,
            fg_color=C["card"],
            corner_radius=10,
            border_width=1,
            border_color=C["border"],
            **kwargs,
        )
        self.db = db
        self.entity_type = entity_type
        self.eid = row_data["id"]
        self.ename = (
            row_data["number"] if entity_type == "vehicle" else row_data["name"]
        )
        row_dict = dict(row_data)
        self._status = row_dict.get("status", "idle")
        self._status_idx = (
            STATUS_ORDER.index(self._status) if self._status in STATUS_ORDER else 0
        )

        self._build(on_delete)
        self._apply_status()

    def _build(self, on_delete):
        self.grid_columnconfigure(1, weight=1)

        self._dot = ctk.CTkLabel(
            self,
            text="●",
            font=ctk.CTkFont(size=18),
            text_color=C["idle"],
            width=30,
            cursor="hand2",
        )
        self._dot.grid(row=0, column=0, padx=(12, 4), pady=12)
        self._dot.bind("<Button-1>", self._cycle_status)

        name_lbl = ctk.CTkLabel(
            self,
            text=self.ename,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C["text"],
            anchor="w",
            cursor="hand2",
        )
        name_lbl.grid(row=0, column=1, sticky="w", padx=4)
        name_lbl.bind("<Button-1>", self._cycle_status)

        self._status_lbl = ctk.CTkLabel(
            self,
            text="В ожидании",
            font=ctk.CTkFont(size=11),
            text_color=C["idle"],
            anchor="w",
        )
        self._status_lbl.grid(row=1, column=1, sticky="w", padx=4, pady=(0, 10))

        ctk.CTkButton(
            self,
            text="✕",
            width=28,
            height=28,
            fg_color="transparent",
            hover_color="#2a1a1a",
            text_color=C["red"],
            font=ctk.CTkFont(size=13),
            command=lambda: on_delete(self),
            corner_radius=6,
        ).grid(row=0, column=2, rowspan=2, padx=(4, 10))

        ctk.CTkFrame(self, height=1, fg_color=C["border"], corner_radius=0).grid(
            row=2, column=0, columnspan=3, sticky="ew"
        )

    def _apply_status(self):
        """Применить текущий статус к визуальным элементам."""
        status = STATUS_ORDER[self._status_idx]
        icon, color, label = STATUS_MAP[status]

        time_str = datetime.now().strftime("%H:%M:%S")
        display = f"{label}  ·  {time_str}" if status != "idle" else "В ожидании"

        self._dot.configure(text=icon, text_color=color)
        self._status_lbl.configure(text=display, text_color=color)
        self.configure(border_color=color if status != "idle" else C["border"])

    def _cycle_status(self, _=None):
        self._status_idx = (self._status_idx + 1) % len(STATUS_ORDER)
        status = STATUS_ORDER[self._status_idx]

        self.db.update_status(self.entity_type, self.eid, status)

        if status in ("arrived", "departed"):
            self.db.log_status(self.entity_type, self.eid, self.ename, status)

        self._apply_status()


class ScrollableCardFrame(ctk.CTkScrollableFrame):
    """Прокручиваемый контейнер для карточек."""

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self._cards: list[EntityCard] = []

    def clear(self):
        for widget in self.winfo_children():
            widget.destroy()
        self._cards.clear()

    def add_card(self, card: EntityCard):
        card.grid(row=len(self._cards), column=0, sticky="ew", padx=4, pady=3)
        self._cards.append(card)
