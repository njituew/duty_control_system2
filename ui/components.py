"""UI-компоненты: EntityTable."""

import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox

from config import C
from database import Database


def _apply_table_style(style_name: str):
    """Применяет тёмную тему к ttk.Treeview."""
    style = ttk.Style()
    style.theme_use("default")
    style.configure(
        f"{style_name}.Treeview",
        background=C["surface"],
        foreground=C["text"],
        fieldbackground=C["surface"],
        borderwidth=0,
        rowheight=38,
        font=("Segoe UI", 11),
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


class EntityTable(tk.Frame):
    """Таблица ТС или командиров на базе ttk.Treeview."""

    _COLUMNS = ("icon", "name", "status", "changed", "del")
    _HEADERS = {
        "icon": "",
        "name": "Наименование",
        "status": "Статус",
        "changed": "Изменён",
        "del": "",
    }
    _WIDTHS = {"icon": 42, "name": 260, "status": 130, "changed": 160, "del": 40}

    _STATUS_DISPLAY = {
        "idle": ("●", C["idle"], "В ожидании"),
        "arrived": ("▲", C["arrived"], "Прибыл"),
        "departed": ("▼", C["departed"], "Убыл"),
    }

    def __init__(self, master, db: Database, entity_type: str, on_changed, **kwargs):
        super().__init__(master, bg=C["bg"], **kwargs)
        self.db = db
        self.entity_type = entity_type
        self._on_changed = on_changed
        self._rows: dict[int, dict] = {}

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        _apply_table_style("Entity")
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
        self._tree.tag_configure("odd", background=C["card"])
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
        self._tooltip_iid: str = ""

    def populate(self, rows):
        """Заполнить таблицу данными."""
        self._rows.clear()
        self._tree.delete(*self._tree.get_children())

        for i, row in enumerate(rows):
            row_dict = dict(row)
            eid = row_dict["id"]
            name = row_dict.get("number") or row_dict.get("name", "")
            status = row_dict.get("status", "idle")
            changed = row_dict.get("updated", row_dict.get("created", ""))
            if len(changed) > 16:
                changed = changed[:16]

            icon, _, label = self._STATUS_DISPLAY.get(
                status, self._STATUS_DISPLAY["idle"]
            )
            zebra = "odd" if i % 2 else "even"
            self._tree.insert(
                "",
                "end",
                iid=str(eid),
                values=(icon, name, label, changed, "🗑"),
                tags=(status, zebra),
            )
            self._rows[eid] = {"status": status, "name": name, "zebra": zebra}

    def _on_click(self, event):
        region = self._tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        iid = self._tree.identify_row(event.y)
        if not iid:
            return

        col_id = self._tree.identify_column(event.x)
        col_name = self._tree.column(col_id, option="id")
        eid = int(iid)

        if col_name == "del":
            self._delete_row(eid)
        else:
            self._toggle_status(eid)

    def _toggle_status(self, eid: int):
        """Переключить статус: arrived ↔ departed."""
        row = self._rows.get(eid)
        if not row:
            return

        current = row["status"]
        new_status = "departed" if current == "arrived" else "arrived"

        self.db.update_status(self.entity_type, eid, new_status)
        self.db.log_status(self.entity_type, eid, row["name"], new_status)

        row["status"] = new_status
        icon, _, label = self._STATUS_DISPLAY[new_status]

        self._tree.item(
            str(eid),
            values=(icon, row["name"], label, _now_short(), "🗑"),
            tags=(new_status, row.get("zebra", "even")),
        )

    def _delete_row(self, eid: int):
        row = self._rows.get(eid)
        if not row:
            return
        name = row["name"]
        if not messagebox.askyesno("Удаление", f"Удалить «{name}»?"):
            return

        if self.entity_type == "vehicle":
            self.db.delete_vehicle(eid)
        else:
            self.db.delete_commander(eid)

        self._tree.delete(str(eid))
        del self._rows[eid]
        self._on_changed()

    def _on_motion(self, event):
        """Сменить курсор при наведении на строку."""
        iid = self._tree.identify_row(event.y)
        if iid != self._tooltip_iid:
            self._tooltip_iid = iid
            cursor = "hand2" if iid else ""
            self._tree.configure(cursor=cursor)

    def row_count(self) -> int:
        return len(self._rows)


def _now_short() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M")
