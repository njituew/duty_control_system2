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

_CARD_COLS  = 3    # columns in the grid
_CARD_PAD   = 10   # gap between cards (px)
_CARD_H     = 82   # card height (px)
_CARD_RADIUS = 4   # corner radius simulation (not native, used for border thickness)


class EntityCardGrid(tk.Frame):
    """Virtualised card grid — draws cards directly on a Canvas.

    No per-card tk widgets are created, so performance is O(visible) not O(total).
    Left-click  — toggle arrived / departed status.
    Right-click — context menu with "Удалить".
    """

    # Fonts (created once, shared across all instances)
    _font_name = None
    _font_sub  = None

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

        # All data lives here — no widgets per card
        # eid -> {name, status, ts}
        self._items: dict[int, dict] = {}
        # Sorted list of eids (display order)
        self._order: list[int] = []

        self._context_menu: tk.Menu | None = None
        self._canvas_w: int = 0
        self._hovered_idx: int = -1

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._init_fonts()
        self._build()

    # ------------------------------------------------------------------
    # Fonts
    # ------------------------------------------------------------------

    def _init_fonts(self) -> None:
        import tkinter.font as tkfont
        if EntityCardGrid._font_name is None:
            EntityCardGrid._font_name = tkfont.Font(family="Segoe UI", size=12, weight="bold")
            EntityCardGrid._font_sub  = tkfont.Font(family="Segoe UI", size=9)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Create the scrollable canvas."""
        self._canvas = tk.Canvas(
            self,
            bg=C["bg"],
            bd=0,
            highlightthickness=0,
        )
        vsb = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._canvas.bind("<Configure>",       self._on_canvas_configure)
        self._canvas.bind("<Button-1>",        self._on_click)
        self._canvas.bind("<Button-2>",        self._on_right)
        self._canvas.bind("<Button-3>",        self._on_right)
        self._canvas.bind("<MouseWheel>",      self._on_mousewheel)
        self._canvas.bind("<Motion>",          self._on_motion)
        self._canvas.bind("<Leave>",           self._on_leave)

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _cell_size(self) -> tuple[int, int]:
        """Return (card_w, row_h) for current canvas width."""
        w = max(self._canvas_w, _CARD_COLS * 20)
        total_pad = _CARD_PAD * (_CARD_COLS + 1)
        card_w = (w - total_pad) // _CARD_COLS
        return card_w, _CARD_H

    def _card_bbox(self, idx: int) -> tuple[int, int, int, int]:
        """Return (x1, y1, x2, y2) canvas coords for card at sorted index *idx*."""
        card_w, card_h = self._cell_size()
        col = idx % _CARD_COLS
        row = idx // _CARD_COLS
        x1 = _CARD_PAD + col * (card_w + _CARD_PAD)
        y1 = _CARD_PAD + row * (card_h + _CARD_PAD)
        return x1, y1, x1 + card_w, y1 + card_h

    def _total_height(self) -> int:
        n = len(self._order)
        if n == 0:
            return 0
        rows = (n + _CARD_COLS - 1) // _CARD_COLS
        _, card_h = self._cell_size()
        return _CARD_PAD + rows * (card_h + _CARD_PAD)

    def _idx_at(self, cx: int, cy: int) -> int:
        """Return sorted index of card under canvas point, or -1."""
        card_w, card_h = self._cell_size()
        col = (cx - _CARD_PAD) // (card_w + _CARD_PAD)
        row = (cy - _CARD_PAD) // (card_h + _CARD_PAD)
        if col < 0 or col >= _CARD_COLS:
            return -1
        idx = row * _CARD_COLS + col
        if idx < 0 or idx >= len(self._order):
            return -1
        # Verify click is inside the card rect, not in padding
        x1, y1, x2, y2 = self._card_bbox(idx)
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            return idx
        return -1

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw_all(self) -> None:
        """Redraw every visible card; skip cards outside the viewport."""
        self._canvas.delete("all")
        if not self._order or self._canvas_w == 0:
            return

        # Visible y range in canvas coords
        yview = self._canvas.yview()
        total_h = self._total_height()
        vis_y0 = int(yview[0] * total_h)
        vis_y1 = int(yview[1] * total_h)
        # Add a one-row buffer above/below
        _, card_h = self._cell_size()
        vis_y0 = max(0, vis_y0 - card_h)
        vis_y1 = vis_y1 + card_h

        for idx, eid in enumerate(self._order):
            x1, y1, x2, y2 = self._card_bbox(idx)
            if y2 < vis_y0 or y1 > vis_y1:
                continue
            self._draw_card(idx, eid, x1, y1, x2, y2)

        self._canvas.configure(scrollregion=(0, 0, self._canvas_w, total_h))

    def _draw_card(self, idx: int, eid: int, x1: int, y1: int, x2: int, y2: int) -> None:
        item = self._items[eid]
        status = item["status"]
        colors = _CARD_STATUS_COLORS.get(status, _CARD_STATUS_COLORS["idle"])
        is_hovered = (idx == self._hovered_idx)

        # Border rect
        border_color = colors["border"]
        if is_hovered:
            # Brighten border slightly on hover
            border_color = colors["text"]
        self._canvas.create_rectangle(
            x1, y1, x2, y2,
            fill=border_color, outline="", tags=("card", f"card_{eid}"),
        )
        # Inner rect (1px inset)
        self._canvas.create_rectangle(
            x1 + 1, y1 + 1, x2 - 1, y2 - 1,
            fill=colors["bg"], outline="", tags=("card", f"card_{eid}"),
        )

        pad_x = x1 + 14
        card_w = x2 - x1
        # Name label — clipped to card width with ellipsis
        self._canvas.create_text(
            pad_x, y1 + 20,
            text=item["name"],
            fill=colors["text"],
            font=EntityCardGrid._font_name,
            anchor="w",
            width=card_w - 28,
            tags=("card", f"card_{eid}"),
        )
        # Sub labels: status on line 1, timestamp on line 2
        status_label = _STATUS_LABEL.get(status, "В ожидании")
        if status != "idle":
            self._canvas.create_text(
                pad_x, y1 + 46,
                text=status_label,
                fill=colors["sub"],
                font=EntityCardGrid._font_sub,
                anchor="w",
                tags=("card", f"card_{eid}"),
            )
            self._canvas.create_text(
                pad_x, y1 + 62,
                text=item["ts"],
                fill=colors["sub"],
                font=EntityCardGrid._font_sub,
                anchor="w",
                tags=("card", f"card_{eid}"),
            )
        else:
            self._canvas.create_text(
                pad_x, y1 + 54,
                text=status_label,
                fill=colors["sub"],
                font=EntityCardGrid._font_sub,
                anchor="w",
                tags=("card", f"card_{eid}"),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def populate(self, rows) -> None:
        """Replace all cards with *rows* data (sorted alphabetically)."""
        self._items.clear()

        rows_list = [dict(r) for r in rows]
        rows_list.sort(key=lambda r: (r.get("number") or r.get("name") or "").lower())

        for row in rows_list:
            eid = row["id"]
            name = row.get("number") or row.get("name", "")
            status = row.get("status", "idle")
            raw_ts = row.get("updated") or row.get("created", "")
            try:
                dt = datetime.strptime(raw_ts[:16], "%Y-%m-%d %H:%M")
                ts = dt.strftime("%H:%M %d.%m.%Y")
            except (ValueError, TypeError):
                ts = raw_ts[:16] if raw_ts else "—"
            self._items[eid] = {"name": name, "status": status, "ts": ts}

        self._rebuild_order()
        self._draw_all()

    def row_count(self) -> int:
        """Return number of currently displayed cards."""
        return len(self._items)

    def _rebuild_order(self) -> None:
        """Rebuild sorted display order from _items."""
        self._order = sorted(
            self._items.keys(),
            key=lambda eid: self._items[eid]["name"].lower(),
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _canvas_y(self, event_y: int) -> int:
        """Convert widget Y to canvas (scrolled) Y."""
        total_h = self._total_height()
        yview = self._canvas.yview()
        return event_y + int(yview[0] * total_h)

    def _on_canvas_configure(self, event) -> None:
        self._canvas_w = event.width
        self._draw_all()

    def _on_mousewheel(self, event) -> None:
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._draw_all()

    def _on_motion(self, event) -> None:
        cy = self._canvas_y(event.y)
        idx = self._idx_at(event.x, cy)
        if idx != self._hovered_idx:
            self._hovered_idx = idx
            self._canvas.configure(cursor="hand2" if idx >= 0 else "")
            self._draw_all()

    def _on_leave(self, _event) -> None:
        if self._hovered_idx != -1:
            self._hovered_idx = -1
            self._canvas.configure(cursor="")
            self._draw_all()

    def _on_click(self, event) -> None:
        cy = self._canvas_y(event.y)
        idx = self._idx_at(event.x, cy)
        if idx < 0:
            return
        eid = self._order[idx]
        self._toggle_status(eid)

    def _on_right(self, event) -> None:
        cy = self._canvas_y(event.y)
        idx = self._idx_at(event.x, cy)
        if idx < 0:
            return
        eid = self._order[idx]
        self._show_context_menu(eid, event)

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------

    def _toggle_status(self, eid: int) -> None:
        item = self._items.get(eid)
        if not item:
            return
        new_status = "departed" if item["status"] == "arrived" else "arrived"
        try:
            self.db.update_status_and_log(self.entity_type, eid, item["name"], new_status)
        except DatabaseError as exc:
            messagebox.showerror("Ошибка", str(exc))
            return
        ts = datetime.now().strftime("%H:%M %d.%m.%Y")
        item["status"] = new_status
        item["ts"] = ts
        self._draw_all()
        self._on_changed()

    def _show_context_menu(self, eid: int, event) -> None:
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
        menu.add_command(label="🗑  Удалить", command=lambda: self._delete_card(eid))
        self._context_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _delete_card(self, eid: int) -> None:
        item = self._items.get(eid)
        if not item:
            return
        if not messagebox.askyesno("Удаление", f"Удалить «{item['name']}»?"):
            return
        try:
            if self.entity_type == "vehicle":
                self.db.delete_vehicle(eid)
            else:
                self.db.delete_commander(eid)
        except (DatabaseError, NotFoundError) as exc:
            messagebox.showerror("Ошибка", str(exc))
            return
        del self._items[eid]
        self._rebuild_order()
        self._draw_all()
        self._on_changed()


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
