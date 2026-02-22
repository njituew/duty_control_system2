"""UI-компоненты: EntityTable, EventTreeview."""

import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from tkinter import messagebox

from config import C, EVENT_COLORS
from database import Database


# ─────────────────────────── Стили Treeview ───────────────────────────────────

def apply_treeview_style(style_name: str, row_height: int = 38, font_size: int = 11):
    """Применяет тёмную тему к ttk.Treeview с заданным именем стиля."""
    style = ttk.Style()
    style.theme_use("default")
    style.configure(
        f"{style_name}.Treeview",
        background=C["surface"],
        foreground=C["text"],
        fieldbackground=C["surface"],
        borderwidth=0,
        rowheight=row_height,
        font=("Segoe UI", font_size),
    )
    style.configure(
        f"{style_name}.Treeview.Heading",
        background=C["card"],
        foreground=C["subtext"],
        borderwidth=0,
        font=("Segoe UI", 10, "bold"),
        padding=(8, 6),
    )
    style.map(
        f"{style_name}.Treeview",
        background=[("selected", C["border"])],
        foreground=[("selected", C["text"])],
    )
    style.map(f"{style_name}.Treeview.Heading", relief=[("active", "flat")])
    style.configure(
        f"{style_name}.Vertical.TScrollbar",
        background=C["border"],
        troughcolor=C["surface"],
        arrowcolor=C["subtext"],
        borderwidth=0,
    )


# ─────────────────────────── EventTreeview ────────────────────────────────────

class EventTreeview(tk.Frame):
    """
    Переиспользуемый виджет таблицы событий (история, статистика).

    Параметры
    ---------
    heading_color : цвет заголовков (по умолчанию subtext, для истории — accent)
    row_height    : высота строки
    """

    _COLUMNS = ("ts", "type", "name", "event")
    _HEADERS = {"ts": "Время", "type": "Тип", "name": "Наименование", "event": "Событие"}
    _WIDTHS   = {"ts": 160, "type": 100, "name": 260, "event": 120}

    _instance_count = 0  # Для уникальных имён стилей

    def __init__(self, master, heading_color: str = C["accent"], row_height: int = 28, **kwargs):
        super().__init__(master, bg=C["surface"], bd=0, highlightthickness=0, **kwargs)

        EventTreeview._instance_count += 1
        self._style_name = f"Events{EventTreeview._instance_count}"

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build(heading_color, row_height)

    def _build(self, heading_color: str, row_height: int):
        apply_treeview_style(self._style_name, row_height=row_height, font_size=10)

        # Переопределяем цвет заголовков после базового стиля
        ttk.Style().configure(
            f"{self._style_name}.Treeview.Heading",
            foreground=heading_color,
        )

        self._tree = ttk.Treeview(
            self,
            columns=self._COLUMNS,
            show="headings",
            style=f"{self._style_name}.Treeview",
            selectmode="browse",
        )

        for col in self._COLUMNS:
            self._tree.heading(col, text=self._HEADERS[col])
            self._tree.column(col, width=self._WIDTHS[col], minwidth=60, anchor="w")

        for event_type, color in EVENT_COLORS.items():
            self._tree.tag_configure(event_type, foreground=color)
        self._tree.tag_configure("default", foreground=C["text"])

        vsb = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self._tree.yview,
            style=f"{self._style_name}.Vertical.TScrollbar",
        )
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

    def populate(self, rows):
        """Заполняет таблицу списком событий из БД."""
        from config import TYPE_LABELS, EVENT_LABELS

        self._tree.delete(*self._tree.get_children())
        for ev in rows:
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


# ─────────────────────────── EntityTable ──────────────────────────────────────

class EntityTable(tk.Frame):
    """Таблица ТС или командиров на базе ttk.Treeview."""

    _COLUMNS = ("icon", "name", "status", "changed", "del")
    _HEADERS = {
        "icon":    "",
        "name":    "Наименование",
        "status":  "Статус",
        "changed": "Изменён",
        "del":     "",
    }
    _WIDTHS = {"icon": 42, "name": 260, "status": 130, "changed": 160, "del": 40}

    _STATUS_DISPLAY = {
        "idle":     ("●", C["idle"],    "В ожидании"),
        "arrived":  ("▲", C["arrived"], "Прибыл"),
        "departed": ("▼", C["departed"],"Убыл"),
    }

    def __init__(self, master, db: Database, entity_type: str, on_changed, **kwargs):
        super().__init__(master, bg=C["bg"], **kwargs)
        self.db = db
        self.entity_type = entity_type
        self._on_changed = on_changed
        self._rows: dict[int, dict] = {}

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        apply_treeview_style("Entity")
        self._build()

    def _build(self):
        container = tk.Frame(self, bg=C["surface"], bd=0, highlightthickness=0)
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            container,
            columns=self._COLUMNS,
            show="headings",
            style="Entity.Treeview",
            selectmode="browse",
        )

        for col in self._COLUMNS:
            self._tree.heading(col, text=self._HEADERS[col])
            self._tree.column(
                col,
                width=self._WIDTHS[col],
                minwidth=self._WIDTHS[col],
                anchor="center" if col in ("icon", "del") else "w",
                stretch=(col == "name"),
            )

        for status, (_, color, _) in self._STATUS_DISPLAY.items():
            self._tree.tag_configure(status, foreground=color)
        self._tree.tag_configure("odd",  background=C["card"])
        self._tree.tag_configure("even", background=C["surface"])

        vsb = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self._tree.yview,
            style="Entity.Vertical.TScrollbar",
        )
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._tree.bind("<ButtonRelease-1>", self._on_click)
        self._tree.bind(
            "<<TreeviewSelect>>",
            lambda _: self._tree.selection_remove(*self._tree.selection()),
        )
        self._tree.bind("<Motion>", self._on_motion)
        self._hovered_iid: str = ""

    def populate(self, rows):
        """Заполняет таблицу данными."""
        self._rows.clear()
        self._tree.delete(*self._tree.get_children())

        for i, row in enumerate(rows):
            row_dict = dict(row)
            eid    = row_dict["id"]
            name   = row_dict.get("number") or row_dict.get("name", "")
            status = row_dict.get("status", "idle")
            ts     = row_dict.get("updated", row_dict.get("created", ""))[:16]

            icon, _, label = self._STATUS_DISPLAY.get(status, self._STATUS_DISPLAY["idle"])
            zebra = "odd" if i % 2 else "even"

            self._tree.insert(
                "", "end",
                iid=str(eid),
                values=(icon, name, label, ts, "🗑"),
                tags=(status, zebra),
            )
            self._rows[eid] = {"status": status, "name": name, "zebra": zebra}

    def _on_click(self, event):
        if self._tree.identify_region(event.x, event.y) != "cell":
            return

        iid = self._tree.identify_row(event.y)
        if not iid:
            return

        col_id   = self._tree.identify_column(event.x)
        col_name = self._tree.column(col_id, option="id")
        eid      = int(iid)

        if col_name == "del":
            self._delete_row(eid)
        else:
            self._toggle_status(eid)

    def _toggle_status(self, eid: int):
        """Переключает статус: arrived ↔ departed."""
        row = self._rows.get(eid)
        if not row:
            return

        new_status = "departed" if row["status"] == "arrived" else "arrived"
        self.db.update_status_and_log(self.entity_type, eid, row["name"], new_status)

        row["status"] = new_status
        icon, _, label = self._STATUS_DISPLAY[new_status]
        ts_short = datetime.now().strftime("%Y-%m-%d %H:%M")

        self._tree.item(
            str(eid),
            values=(icon, row["name"], label, ts_short, "🗑"),
            tags=(new_status, row["zebra"]),
        )

    def _delete_row(self, eid: int):
        row = self._rows.get(eid)
        if not row:
            return

        if not messagebox.askyesno("Удаление", f"Удалить «{row['name']}»?"):
            return

        if self.entity_type == "vehicle":
            self.db.delete_vehicle(eid)
        else:
            self.db.delete_commander(eid)

        self._tree.delete(str(eid))
        del self._rows[eid]
        self._on_changed()

    def _on_motion(self, event):
        """Меняет курсор при наведении на строку."""
        iid = self._tree.identify_row(event.y)
        if iid != self._hovered_iid:
            self._hovered_iid = iid
            self._tree.configure(cursor="hand2" if iid else "")

    def row_count(self) -> int:
        return len(self._rows)
