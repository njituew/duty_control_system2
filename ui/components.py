"""Reusable UI components: EntityCardGrid, EntityTable and EventTreeview."""

import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from tkinter import messagebox

from config import C, EVENT_COLORS
from database import Database, DatabaseError, NotFoundError


def apply_treeview_style(
    style_name: str, row_height: int = 38, font_size: int = 11
) -> None:
    """Configure a dark ttk.Treeview style under the given name prefix.

    Args:
        style_name: Prefix used to namespace the style, e.g. 'Entity'.
        row_height: Height of each data row in pixels.
        font_size: Font size for cell text.
    """
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


class EventTreeview(tk.Frame):
    """Read-only table for displaying event log entries."""

    _COLUMNS = ("ts", "type", "name", "event")
    _HEADERS = {
        "ts": "Время",
        "type": "Тип",
        "name": "Наименование",
        "event": "Событие",
    }
    _WIDTHS = {"ts": 160, "type": 100, "name": 260, "event": 120}

    # Unique counter used to avoid ttk style name collisions across instances.
    _instance_count = 0

    def __init__(
        self, master, heading_color: str = C["accent"], row_height: int = 28, **kwargs
    ):
        super().__init__(master, bg=C["surface"], bd=0, highlightthickness=0, **kwargs)

        EventTreeview._instance_count += 1
        self._style_name = f"Events{EventTreeview._instance_count}"

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build(heading_color, row_height)

    def _build(self, heading_color: str, row_height: int) -> None:
        apply_treeview_style(self._style_name, row_height=row_height, font_size=10)

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

    @staticmethod
    def _fmt_ts(ts: str) -> str:
        """Convert an ISO timestamp to the display format 'HH:MM DD.MM.YYYY'."""
        try:
            dt = datetime.strptime(ts[:16], "%Y-%m-%d %H:%M")
            return dt.strftime("%H:%M %d.%m.%Y")
        except (ValueError, TypeError):
            return ts

    def populate(self, rows) -> None:
        """Replace all rows with the given event records.

        Args:
            rows: Iterable of sqlite3.Row objects from the events table.
        """
        from config import TYPE_LABELS, EVENT_LABELS

        self._tree.delete(*self._tree.get_children())
        for ev in rows:
            tag = ev["event_type"] if ev["event_type"] in EVENT_COLORS else "default"
            self._tree.insert(
                "",
                "end",
                values=(
                    self._fmt_ts(ev["ts"]),
                    TYPE_LABELS.get(ev["entity_type"], ev["entity_type"]),
                    ev["entity_name"],
                    EVENT_LABELS.get(ev["event_type"], ev["event_type"]),
                ),
                tags=(tag,),
            )


# ---------------------------------------------------------------------------
# Card-grid colours per status
# ---------------------------------------------------------------------------
_CARD_STATUS_COLORS = {
    "idle":     {"bg": "#1e2130", "border": "#2a2d3e", "text": C["text"],     "sub": C["subtext"]},
    "arrived":  {"bg": "#0d2318", "border": "#3dd68c", "text": C["arrived"],  "sub": "#2a9c65"},
    "departed": {"bg": "#280f0f", "border": "#f75f5f", "text": C["departed"], "sub": "#9c2a2a"},
}

_STATUS_LABEL = {
    "idle":     "В ожидании",
    "arrived":  "Прибыл(а) в",
    "departed": "Убыл(а) в",
}

_CARD_W = 200   # fixed card width
_CARD_H = 76    # fixed card height
_CARD_COLS = 3  # number of columns in the grid
_CARD_PAD = 10  # gap between cards


class EntityCardGrid(tk.Frame):
    """Interactive card grid for vehicles or commanders.

    Left-click  — toggle arrived / departed status.
    Right-click — context menu with "Удалить".
    """

    def __init__(
        self,
        master,
        db: Database,
        entity_type: str,
        on_changed=None,
        **kwargs,
    ):
        super().__init__(master, bg=C["bg"], **kwargs)
        self.db = db
        self.entity_type = entity_type
        self._on_changed = on_changed or (lambda: None)
        self._rows: dict[int, dict] = {}      # eid -> {status, name, frame, ...}
        self._context_menu: tk.Menu | None = None

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Create the scrollable canvas that hosts all cards."""
        canvas_frame = tk.Frame(self, bg=C["bg"])
        canvas_frame.grid(row=0, column=0, sticky="nsew")
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(
            canvas_frame,
            bg=C["bg"],
            bd=0,
            highlightthickness=0,
        )
        vsb = tk.Scrollbar(canvas_frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # Inner frame that holds all card widgets
        self._inner = tk.Frame(self._canvas, bg=C["bg"])
        self._inner_id = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw"
        )

        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_inner_configure(self, _event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfigure(self._inner_id, width=event.width)

    def _on_mousewheel(self, event) -> None:
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def populate(self, rows) -> None:
        """Replace all cards with data from *rows*."""
        # Destroy existing cards
        for widget in self._inner.winfo_children():
            widget.destroy()
        self._rows.clear()

        for i, row in enumerate(rows):
            row_dict = dict(row)
            eid = row_dict["id"]
            name = row_dict.get("number") or row_dict.get("name", "")
            status = row_dict.get("status", "idle")
            raw_ts = row_dict.get("updated", row_dict.get("created", ""))
            try:
                dt = datetime.strptime(raw_ts[:16], "%Y-%m-%d %H:%M")
                ts = dt.strftime("%H:%M %d.%m.%Y")
            except (ValueError, TypeError):
                ts = raw_ts[:16] if raw_ts else "—"

            card_frame = self._make_card(eid, name, status, ts)
            col = i % _CARD_COLS
            row_idx = i // _CARD_COLS
            card_frame.grid(
                row=row_idx,
                column=col,
                padx=_CARD_PAD,
                pady=_CARD_PAD,
                sticky="nsew",
            )
            self._rows[eid] = {
                "status": status,
                "name": name,
                "ts": ts,
                "frame": card_frame,
                "grid_pos": (row_idx, col),
            }

        # Make all columns equally wide
        for c in range(_CARD_COLS):
            self._inner.grid_columnconfigure(c, weight=1)

    def row_count(self) -> int:
        """Return number of currently displayed cards."""
        return len(self._rows)

    # ------------------------------------------------------------------
    # Card creation
    # ------------------------------------------------------------------

    def _make_card(
        self,
        eid: int,
        name: str,
        status: str,
        ts: str,
    ) -> tk.Frame:
        """Build and return a single card frame."""
        colors = _CARD_STATUS_COLORS.get(status, _CARD_STATUS_COLORS["idle"])

        outer = tk.Frame(
            self._inner,
            bg=colors["border"],
            cursor="hand2",
        )
        # 1-px border effect using padding inside outer
        inner = tk.Frame(
            outer,
            bg=colors["bg"],
            padx=12,
            pady=8,
        )
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Main label (name / number)
        name_lbl = tk.Label(
            inner,
            text=name,
            bg=colors["bg"],
            fg=colors["text"],
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        )
        name_lbl.pack(fill="x")

        # Status sub-label
        status_label = _STATUS_LABEL.get(status, "В ожидании")
        if status != "idle":
            sub_text = f"{status_label} {ts}"
        else:
            sub_text = status_label

        sub_lbl = tk.Label(
            inner,
            text=sub_text,
            bg=colors["bg"],
            fg=colors["sub"],
            font=("Segoe UI", 9),
            anchor="w",
        )
        sub_lbl.pack(fill="x")

        # Store label references so we can update them on status change
        outer._eid = eid          # type: ignore[attr-defined]
        outer._name_lbl = name_lbl   # type: ignore[attr-defined]
        outer._sub_lbl = sub_lbl     # type: ignore[attr-defined]
        outer._inner_f = inner       # type: ignore[attr-defined]

        # Bind events to all children
        for widget in (outer, inner, name_lbl, sub_lbl):
            widget.bind("<Button-1>", lambda e, _eid=eid: self._on_left_click(_eid))
            widget.bind("<Button-2>", lambda e, _eid=eid: self._on_right_click(_eid, e))
            widget.bind("<Button-3>", lambda e, _eid=eid: self._on_right_click(_eid, e))

        return outer

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    def _on_left_click(self, eid: int) -> None:
        """Toggle arrived / departed status."""
        row = self._rows.get(eid)
        if not row:
            return

        new_status = "departed" if row["status"] == "arrived" else "arrived"
        try:
            self.db.update_status_and_log(
                self.entity_type, eid, row["name"], new_status
            )
        except DatabaseError as e:
            messagebox.showerror("Ошибка", str(e))
            return

        ts = datetime.now().strftime("%H:%M %d.%m.%Y")
        row["status"] = new_status
        row["ts"] = ts
        self._update_card_appearance(eid, new_status, ts)
        self._on_changed()

    def _on_right_click(self, eid: int, event) -> None:
        """Show context menu with delete option."""
        # Destroy any previous menu
        if self._context_menu:
            try:
                self._context_menu.destroy()
            except Exception:
                pass

        menu = tk.Menu(
            self,
            tearoff=0,
            bg=C["surface"],
            fg=C["text"],
            activebackground=C["card"],
            activeforeground=C["red"],
            font=("Segoe UI", 11),
            bd=0,
            relief="flat",
        )
        menu.add_command(
            label="🗑  Удалить",
            command=lambda: self._delete_card(eid),
        )
        self._context_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _delete_card(self, eid: int) -> None:
        """Ask for confirmation and delete the entity."""
        row = self._rows.get(eid)
        if not row:
            return

        if not messagebox.askyesno("Удаление", f"Удалить «{row['name']}»?"):
            return

        try:
            if self.entity_type == "vehicle":
                self.db.delete_vehicle(eid)
            else:
                self.db.delete_commander(eid)
        except (DatabaseError, NotFoundError) as e:
            messagebox.showerror("Ошибка", str(e))
            return

        frame = row["frame"]
        frame.destroy()
        del self._rows[eid]
        self._on_changed()

    def _update_card_appearance(self, eid: int, status: str, ts: str) -> None:
        """Repaint a card to reflect a new status."""
        row = self._rows.get(eid)
        if not row:
            return

        colors = _CARD_STATUS_COLORS.get(status, _CARD_STATUS_COLORS["idle"])
        card = row["frame"]

        card.configure(bg=colors["border"])
        card._inner_f.configure(bg=colors["bg"])   # type: ignore[attr-defined]
        card._name_lbl.configure(bg=colors["bg"], fg=colors["text"])  # type: ignore[attr-defined]

        status_label = _STATUS_LABEL.get(status, "В ожидании")
        if status != "idle":
            sub_text = f"{status_label} {ts}"
        else:
            sub_text = status_label

        card._sub_lbl.configure(  # type: ignore[attr-defined]
            bg=colors["bg"],
            fg=colors["sub"],
            text=sub_text,
        )


class EntityTable(tk.Frame):
    """Interactive table for vehicles or commanders with inline status toggling."""

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

        apply_treeview_style("Entity")
        self._build()

    def _build(self) -> None:
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

        self._tree.bind("<Button-1>", self._on_press)
        self._tree.bind("<ButtonRelease-1>", self._on_click)
        self._tree.bind(
            "<<TreeviewSelect>>",
            lambda _: self._tree.selection_remove(*self._tree.selection()),
        )
        self._tree.bind("<Motion>", self._on_motion)
        self._hovered_iid: str = ""
        self._press_iid: str = ""

    def populate(self, rows) -> None:
        """Replace all rows with the given entity records."""
        self._rows.clear()
        self._tree.delete(*self._tree.get_children())

        for i, row in enumerate(rows):
            row_dict = dict(row)
            eid = row_dict["id"]
            name = row_dict.get("number") or row_dict.get("name", "")
            status = row_dict.get("status", "idle")
            raw_ts = row_dict.get("updated", row_dict.get("created", ""))
            try:
                dt = datetime.strptime(raw_ts[:16], "%Y-%m-%d %H:%M")
                ts = dt.strftime("%H:%M %d.%m.%Y")
            except (ValueError, TypeError):
                ts = raw_ts[:16]

            icon, _, label = self._STATUS_DISPLAY.get(
                status, self._STATUS_DISPLAY["idle"]
            )
            zebra = "odd" if i % 2 else "even"

            self._tree.insert(
                "",
                "end",
                iid=str(eid),
                values=(icon, name, label, ts, "🗑"),
                tags=(status, zebra),
            )
            self._rows[eid] = {"status": status, "name": name, "zebra": zebra}

    def _on_press(self, event) -> None:
        self._press_iid = self._tree.identify_row(event.y)

    def _on_click(self, event) -> None:
        iid = self._tree.identify_row(event.y)
        if not iid or iid != self._press_iid:
            self._press_iid = ""
            return
        self._press_iid = ""

        if self._tree.identify_region(event.x, event.y) != "cell":
            return

        col_id = self._tree.identify_column(event.x)
        col_name = self._tree.column(col_id, option="id")
        eid = int(iid)

        if col_name == "del":
            self._delete_row(eid)
        else:
            self._toggle_status(eid)

    def _toggle_status(self, eid: int) -> None:
        row = self._rows.get(eid)
        if not row:
            return

        new_status = "departed" if row["status"] == "arrived" else "arrived"
        try:
            self.db.update_status_and_log(
                self.entity_type, eid, row["name"], new_status
            )
        except DatabaseError as e:
            messagebox.showerror("Ошибка", str(e))
            return

        row["status"] = new_status
        icon, _, label = self._STATUS_DISPLAY[new_status]
        ts_short = datetime.now().strftime("%H:%M %d.%m.%Y")

        self._tree.item(
            str(eid),
            values=(icon, row["name"], label, ts_short, "🗑"),
            tags=(new_status, row["zebra"]),
        )

    def _delete_row(self, eid: int) -> None:
        row = self._rows.get(eid)
        if not row:
            return

        if not messagebox.askyesno("Удаление", f"Удалить «{row['name']}»?"):
            return

        try:
            if self.entity_type == "vehicle":
                self.db.delete_vehicle(eid)
            else:
                self.db.delete_commander(eid)
        except (DatabaseError, NotFoundError) as e:
            messagebox.showerror("Ошибка", str(e))
            return

        self._tree.delete(str(eid))
        del self._rows[eid]
        self._on_changed()

    def _on_motion(self, event) -> None:
        iid = self._tree.identify_row(event.y)
        if iid != self._hovered_iid:
            self._hovered_iid = iid
            self._tree.configure(cursor="hand2" if iid else "")

    def row_count(self) -> int:
        return len(self._rows)
