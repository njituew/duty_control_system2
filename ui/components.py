"""Reusable UI components: EntityCardGrid and EventTreeview."""

import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk
from datetime import datetime
from tkinter import messagebox

from config import EVENT_COLORS, EVENT_LABELS, STATUS_ORDER, TYPE_LABELS, C
from database import Database, DatabaseError, NotFoundError


def fmt_timestamp(raw: str) -> str:
    """Parse a stored ISO timestamp and return 'HH:MM DD.MM.YYYY', or '—' on failure."""
    try:
        dt = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
        return dt.strftime("%H:%M %d.%m.%Y")
    except (ValueError, TypeError):
        return raw[:16] if raw else "—"


def apply_treeview_style(
    style_name: str, row_height: int = 38, font_size: int = 11
) -> None:
    """Register a dark ttk.Treeview style under the given name prefix."""
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

    def __init__(
        self, master, heading_color: str = C["accent"], row_height: int = 28, **kwargs
    ):
        super().__init__(master, bg=C["surface"], bd=0, highlightthickness=0, **kwargs)
        # id(self) gives a unique style name without a mutable class-level counter.
        self._style_name = f"Events{id(self)}"
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build(heading_color, row_height)

    def _build(self, heading_color: str, row_height: int) -> None:
        apply_treeview_style(self._style_name, row_height=row_height, font_size=10)
        ttk.Style().configure(
            f"{self._style_name}.Treeview.Heading", foreground=heading_color
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

    def populate(self, rows) -> None:
        """Replace all rows with the given dataset."""
        self._tree.delete(*self._tree.get_children())
        for ev in rows:
            tag = ev["event_type"] if ev["event_type"] in EVENT_COLORS else "default"
            self._tree.insert(
                "",
                "end",
                values=(
                    fmt_timestamp(ev["ts"]),
                    TYPE_LABELS.get(ev["entity_type"], ev["entity_type"]),
                    ev["entity_name"],
                    EVENT_LABELS.get(ev["event_type"], ev["event_type"]),
                ),
                tags=(tag,),
            )


# Per-status visual theme for cards: background, border, text, and subdued text colors.
_CARD_STATUS_COLORS: dict[str, dict[str, str]] = {
    "idle": {
        "bg": "#1e2130",
        "border": "#2a2d3e",
        "text": C["text"],
        "sub": C["subtext"],
    },
    "arrived": {
        "bg": "#0d2318",
        "border": "#3dd68c",
        "text": C["arrived"],
        "sub": "#2a9c65",
    },
    "departed": {
        "bg": "#280f0f",
        "border": "#f75f5f",
        "text": C["departed"],
        "sub": "#9c2a2a",
    },
}

# Status label text differs slightly between vehicles and commanders (grammatical gender).
_STATUS_LABEL: dict[str, dict[str, str]] = {
    "vehicle": {
        "idle": "В ожидании",
        "arrived": "Прибыло в",
        "departed": "Убыло в",
    },
    "commander": {
        "idle": "В ожидании",
        "arrived": "Прибыл(а) в",
        "departed": "Убыл(а) в",
    },
}

_CARD_COLS = 3
_CARD_PAD = 10
_CARD_H = 82  # card height in pixels

_CARD_TEXT_PAD_X = 14  # horizontal inset from the left card edge
_CARD_NAME_Y = 20  # Y offset of the name label from the card top
_CARD_STATUS_Y_SINGLE = 54  # Y for the status line when there is only one line (idle)
_CARD_STATUS_Y_DOUBLE = 46  # Y for the status line when a timestamp follows below it
_CARD_TIME_Y = 62  # Y for the timestamp line


class EntityCardGrid(tk.Frame):
    """Interactive card grid backed by a scrolling tk.Canvas.

    Cards are drawn as Canvas rectangles and text items for performance.
    populate() rebuilds the whole grid in O(N); hover and click update
    only the affected card via O(1) itemconfigure calls.
    """

    _font_name: tkfont.Font | None = None
    _font_sub: tkfont.Font | None = None
    _font_name_sm: tkfont.Font | None = None  # used for names longer than 18 chars

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

        self._items: dict[int, dict] = {}  # eid → card data + canvas item ids
        self._order: list[int] = []  # sorted list of eids
        self._idx_to_eid: list[int] = []  # position → eid
        self._eid_to_idx: dict[int, int] = {}  # eid → position

        self._canvas_w: int = 0
        self._hovered_eid: int = -1
        self._context_menu: tk.Menu | None = None

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._init_fonts()
        self._build()

    def _init_fonts(self) -> None:
        """Initialise shared class-level Font objects on first instantiation."""
        if EntityCardGrid._font_name is None:
            EntityCardGrid._font_name = tkfont.Font(
                family="Segoe UI", size=11, weight="bold"
            )
            EntityCardGrid._font_name_sm = tkfont.Font(
                family="Segoe UI", size=9, weight="bold"
            )
            EntityCardGrid._font_sub = tkfont.Font(family="Segoe UI", size=9)

    def _build(self) -> None:
        self._canvas = tk.Canvas(self, bg=C["bg"], bd=0, highlightthickness=0)
        vsb = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._canvas.bind("<Configure>", self._on_configure)
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Button-2>", self._on_right)
        self._canvas.bind("<Button-3>", self._on_right)
        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<Leave>", self._on_leave)
        self._canvas.focus_set()
        self._canvas.bind("<Shift-MouseWheel>", lambda _e: None)
        self._canvas.bind("<Enter>", self._on_canvas_enter)
        self._canvas.bind("<Leave>", self._on_canvas_leave)

    def _on_canvas_enter(self, _event) -> None:
        # Activate mouse-wheel scrolling only while the cursor is over this canvas.
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_canvas_leave(self, event) -> None:
        self._canvas.unbind_all("<MouseWheel>")
        self._on_leave(event)

    def _cell_w(self) -> int:
        w = max(self._canvas_w, _CARD_COLS * 30)
        return (w - _CARD_PAD * (_CARD_COLS + 1)) // _CARD_COLS

    def _card_rect(self, idx: int) -> tuple[int, int, int, int]:
        """Return absolute canvas coords (x1, y1, x2, y2) for card at sorted index."""
        cw = self._cell_w()
        col = idx % _CARD_COLS
        row = idx // _CARD_COLS
        x1 = _CARD_PAD + col * (cw + _CARD_PAD)
        y1 = _CARD_PAD + row * (_CARD_H + _CARD_PAD)
        return x1, y1, x1 + cw, y1 + _CARD_H

    def _total_height(self) -> int:
        n = len(self._order)
        if n == 0:
            return 0
        rows = (n + _CARD_COLS - 1) // _CARD_COLS
        return _CARD_PAD + rows * (_CARD_H + _CARD_PAD)

    def _update_scroll_region(self) -> None:
        content_h = self._total_height()
        canvas_h = self._canvas.winfo_height()
        region_h = max(content_h, canvas_h if canvas_h > 1 else 0)
        self._canvas.configure(
            scrollregion=(0, 0, max(self._canvas_w, 1), max(region_h, 1))
        )

    def _canvas_coords(self, event) -> tuple[int, int]:
        """Convert widget-relative mouse coords to absolute canvas coords."""
        return int(self._canvas.canvasx(event.x)), int(self._canvas.canvasy(event.y))

    def _hit_test(self, cx: int, cy: int) -> int:
        """Return the eid of the card under the given canvas point, or -1."""
        cw = self._cell_w()
        if cw <= 0:
            return -1
        col = (cx - _CARD_PAD) // (cw + _CARD_PAD)
        if col < 0 or col >= _CARD_COLS:
            return -1
        row = (cy - _CARD_PAD) // (_CARD_H + _CARD_PAD)
        idx = row * _CARD_COLS + col
        if idx < 0 or idx >= len(self._idx_to_eid):
            return -1
        x1, y1, x2, y2 = self._card_rect(idx)
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            return self._idx_to_eid[idx]
        return -1

    def _card_tag(self, eid: int) -> str:
        return f"c{eid}"

    def _draw_card(self, idx: int, eid: int) -> None:
        """Create all canvas items for a card. Called once per card in populate()."""
        item = self._items[eid]
        status = item["status"]
        colors = _CARD_STATUS_COLORS.get(status, _CARD_STATUS_COLORS["idle"])
        cw = self._cell_w()
        x1, y1, x2, y2 = self._card_rect(idx)
        tag = self._card_tag(eid)
        cv = self._canvas

        item["tag_border"] = cv.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill=colors["border"],
            outline="",
            tags=tag,
        )
        # Inner rect inset by 1 px so the border color is visible around the edge.
        item["tag_bg"] = cv.create_rectangle(
            x1 + 1,
            y1 + 1,
            x2 - 1,
            y2 - 1,
            fill=colors["bg"],
            outline="",
            tags=tag,
        )
        name_font = (
            EntityCardGrid._font_name
            if len(item["name"]) <= 18
            else EntityCardGrid._font_name_sm
        )
        item["tag_name"] = cv.create_text(
            x1 + _CARD_TEXT_PAD_X,
            y1 + _CARD_NAME_Y,
            text=item["name"],
            fill=colors["text"],
            font=name_font,
            anchor="w",
            width=cw - _CARD_TEXT_PAD_X * 2,
            tags=tag,
        )
        status_lbl = _STATUS_LABEL[self.entity_type].get(status, "В ожидании")
        if status != "idle":
            item["tag_sub1"] = cv.create_text(
                x1 + _CARD_TEXT_PAD_X,
                y1 + _CARD_STATUS_Y_DOUBLE,
                text=status_lbl,
                fill=colors["sub"],
                font=EntityCardGrid._font_sub,
                anchor="w",
                tags=tag,
            )
            item["tag_sub2"] = cv.create_text(
                x1 + _CARD_TEXT_PAD_X,
                y1 + _CARD_TIME_Y,
                text=item["ts"],
                fill=colors["sub"],
                font=EntityCardGrid._font_sub,
                anchor="w",
                tags=tag,
            )
        else:
            item["tag_sub1"] = cv.create_text(
                x1 + _CARD_TEXT_PAD_X,
                y1 + _CARD_STATUS_Y_SINGLE,
                text=status_lbl,
                fill=colors["sub"],
                font=EntityCardGrid._font_sub,
                anchor="w",
                tags=tag,
            )
            item["tag_sub2"] = None

    def _repaint_card(self, eid: int) -> None:
        """Update colors and text of an existing card without recreating its items."""
        item = self._items.get(eid)
        if not item:
            return
        status = item["status"]
        colors = _CARD_STATUS_COLORS.get(status, _CARD_STATUS_COLORS["idle"])
        status_lbl = _STATUS_LABEL[self.entity_type].get(status, "В ожидании")
        cv = self._canvas

        cv.itemconfigure(item["tag_border"], fill=colors["border"])
        cv.itemconfigure(item["tag_bg"], fill=colors["bg"])
        cv.itemconfigure(item["tag_name"], fill=colors["text"])

        idx = self._eid_to_idx.get(eid, -1)
        if idx == -1:
            return
        x1, y1, _x2, _y2 = self._card_rect(idx)

        if status != "idle":
            cv.coords(
                item["tag_sub1"], x1 + _CARD_TEXT_PAD_X, y1 + _CARD_STATUS_Y_DOUBLE
            )
            cv.itemconfigure(item["tag_sub1"], text=status_lbl, fill=colors["sub"])
            if item["tag_sub2"] is None:
                # Card was previously idle and had no timestamp item — create it now.
                item["tag_sub2"] = cv.create_text(
                    x1 + _CARD_TEXT_PAD_X,
                    y1 + _CARD_TIME_Y,
                    text=item["ts"],
                    fill=colors["sub"],
                    font=EntityCardGrid._font_sub,
                    anchor="w",
                    tags=self._card_tag(eid),
                )
            else:
                cv.coords(item["tag_sub2"], x1 + _CARD_TEXT_PAD_X, y1 + _CARD_TIME_Y)
                cv.itemconfigure(
                    item["tag_sub2"],
                    text=item["ts"],
                    fill=colors["sub"],
                    state="normal",
                )
        else:
            cv.coords(
                item["tag_sub1"], x1 + _CARD_TEXT_PAD_X, y1 + _CARD_STATUS_Y_SINGLE
            )
            cv.itemconfigure(item["tag_sub1"], text=status_lbl, fill=colors["sub"])
            if item["tag_sub2"] is not None:
                cv.itemconfigure(item["tag_sub2"], state="hidden")

    def _set_hover(self, eid: int, on: bool) -> None:
        item = self._items.get(eid)
        if not item:
            return
        colors = _CARD_STATUS_COLORS.get(item["status"], _CARD_STATUS_COLORS["idle"])
        self._canvas.itemconfigure(
            item["tag_border"],
            fill=colors["text"] if on else colors["border"],
        )

    def _sync_order_index(self) -> None:
        """Rebuild the position ↔ eid lookup tables from _order."""
        self._idx_to_eid = list(self._order)
        self._eid_to_idx = {eid: idx for idx, eid in enumerate(self._order)}

    def populate(self, rows) -> None:
        """Rebuild the entire grid from a fresh row set."""
        self._canvas.delete("all")
        self._items.clear()
        self._order.clear()
        self._idx_to_eid.clear()
        self._eid_to_idx.clear()
        self._hovered_eid = -1

        rows_list = sorted(
            (dict(r) for r in rows),
            key=lambda r: (r.get("number") or r.get("name") or "").lower(),
        )

        for row in rows_list:
            eid = row["id"]
            self._items[eid] = {
                "name": row.get("number") or row.get("name", ""),
                "status": row.get("status", "idle"),
                "ts": fmt_timestamp(row.get("updated") or row.get("created", "")),
                "tag_border": None,
                "tag_bg": None,
                "tag_name": None,
                "tag_sub1": None,
                "tag_sub2": None,
            }
            self._order.append(eid)

        self._sync_order_index()
        for idx, eid in enumerate(self._order):
            self._draw_card(idx, eid)
        self._canvas.after_idle(self._update_scroll_region)

    def row_count(self) -> int:
        return len(self._items)

    def _rebuild_after_delete(self) -> None:
        """Redraw all cards from in-memory data without re-querying the database."""
        self._canvas.delete("all")
        self._order = sorted(
            self._items.keys(),
            key=lambda e: self._items[e]["name"].lower(),
        )
        self._sync_order_index()
        self._hovered_eid = -1
        for idx, eid in enumerate(self._order):
            self._draw_card(idx, eid)
        self._canvas.after_idle(self._update_scroll_region)

    def _on_configure(self, event) -> None:
        new_w = event.width
        if new_w == self._canvas_w:
            return
        self._canvas_w = new_w
        if not self._order:
            self._update_scroll_region()
            return
        # Card width depends on canvas width, so a resize forces a full redraw.
        yview = self._canvas.yview()
        self._canvas.delete("all")
        for idx, eid in enumerate(self._order):
            self._draw_card(idx, eid)
        self._update_scroll_region()
        self._canvas.yview_moveto(yview[0])

    def _on_mousewheel(self, event) -> None:
        delta = event.delta
        units = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        self._canvas.yview_scroll(units, "units")

    def _on_motion(self, event) -> None:
        cx, cy = self._canvas_coords(event)
        eid = self._hit_test(cx, cy)
        if eid == self._hovered_eid:
            return
        if self._hovered_eid != -1:
            self._set_hover(self._hovered_eid, False)
        self._hovered_eid = eid
        if eid != -1:
            self._set_hover(eid, True)
        self._canvas.configure(cursor="hand2" if eid != -1 else "")

    def _on_leave(self, _event) -> None:
        if self._hovered_eid != -1:
            self._set_hover(self._hovered_eid, False)
            self._hovered_eid = -1
        self._canvas.configure(cursor="")

    def _on_click(self, event) -> None:
        cx, cy = self._canvas_coords(event)
        eid = self._hit_test(cx, cy)
        if eid != -1:
            self._toggle_status(eid)

    def _on_right(self, event) -> None:
        cx, cy = self._canvas_coords(event)
        eid = self._hit_test(cx, cy)
        if eid != -1:
            self._show_context_menu(eid, event)

    def _toggle_status(self, eid: int) -> None:
        item = self._items.get(eid)
        if not item:
            return
        current = item["status"]
        if current in STATUS_ORDER:
            new_status = STATUS_ORDER[
                (STATUS_ORDER.index(current) + 1) % len(STATUS_ORDER)
            ]
        else:
            # "idle" is not in the cycle — first click always goes to arrived.
            new_status = STATUS_ORDER[0]
        try:
            self.db.update_status_and_log(
                self.entity_type, eid, item["name"], new_status
            )
        except DatabaseError as exc:
            messagebox.showerror("Ошибка", str(exc))
            return
        item["status"] = new_status
        item["ts"] = datetime.now().strftime("%H:%M %d.%m.%Y")
        self._repaint_card(eid)
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
            self.db.delete_entity(self.entity_type, eid)
        except (DatabaseError, NotFoundError) as exc:
            messagebox.showerror("Ошибка", str(exc))
            return
        del self._items[eid]
        self._rebuild_after_delete()
        self._on_changed()
