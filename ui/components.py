"""Reusable UI components: EntityCardGrid, EntityTable and EventTreeview."""

import tkinter as tk
import tkinter.ttk as ttk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import messagebox

from config import C, EVENT_COLORS
from database import Database, DatabaseError, NotFoundError


def apply_treeview_style(
    style_name: str, row_height: int = 38, font_size: int = 11
) -> None:
    """Configure a dark ttk.Treeview style under the given name prefix."""
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
        from config import TYPE_LABELS, EVENT_LABELS

        self._tree.delete(*self._tree.get_children())
        for ev in rows:
            tag = ev["event_type"] if ev["event_type"] in EVENT_COLORS else "default"
            self._tree.insert(
                "",
                "end",
                values=(
                    _fmt_timestamp(ev["ts"]),
                    TYPE_LABELS.get(ev["entity_type"], ev["entity_type"]),
                    ev["entity_name"],
                    EVENT_LABELS.get(ev["event_type"], ev["event_type"]),
                ),
                tags=(tag,),
            )


def _fmt_timestamp(raw: str) -> str:
    """Parse an ISO-ish timestamp and return 'HH:MM DD.MM.YYYY', or '—'."""
    try:
        dt = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
        return dt.strftime("%H:%M %d.%m.%Y")
    except (ValueError, TypeError):
        return raw[:16] if raw else "—"


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
_CARD_H = 82  # card height px


class EntityCardGrid(tk.Frame):
    """Interactive card grid backed by a native-scrolling tk.Canvas.

    populate()    — O(N) full rebuild.
    scroll        — O(1), handled entirely by Tk.
    hover / click — O(1), itemconfigure on the touched card only.
    """

    _font_name: tkfont.Font | None = None
    _font_sub: tkfont.Font | None = None
    _font_name_sm: tkfont.Font | None = None  # smaller variant for long names

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

        self._items: dict[int, dict] = {}
        self._order: list[int] = []  # sorted display order

        self._idx_to_eid: list[int] = []

        self._canvas_w: int = 0  # last known canvas pixel width
        self._hovered_eid: int = -1

        self._context_menu: tk.Menu | None = None

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._init_fonts()
        self._build()

    def _init_fonts(self) -> None:
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

        # bind_all so the wheel fires even without keyboard focus
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind_all("<Shift-MouseWheel>", lambda _e: None)

        # Local fallback bind
        self._canvas.bind("<MouseWheel>", self._on_mousewheel_local)

    def _cell_w(self) -> int:
        w = max(self._canvas_w, _CARD_COLS * 30)
        return (w - _CARD_PAD * (_CARD_COLS + 1)) // _CARD_COLS

    def _card_rect(self, idx: int) -> tuple[int, int, int, int]:
        """Absolute canvas coords (x1,y1,x2,y2) for card at sorted index."""
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

    def _canvas_coords(self, event) -> tuple[int, int]:
        """Convert a widget-relative event to absolute canvas coords."""
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        return int(cx), int(cy)

    def _hit_test(self, cx: int, cy: int) -> int:
        """Return eid of card under canvas point, or -1."""
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
        # verify point is inside card body, not in padding gap
        x1, y1, x2, y2 = self._card_rect(idx)
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            return self._idx_to_eid[idx]
        return -1

    def _card_tag(self, eid: int) -> str:
        return f"c{eid}"

    def _draw_card(self, idx: int, eid: int) -> None:
        """Create all canvas items for one card. Called once per card at populate."""
        item = self._items[eid]
        status = item["status"]
        colors = _CARD_STATUS_COLORS.get(status, _CARD_STATUS_COLORS["idle"])
        cw = self._cell_w()
        x1, y1, x2, y2 = self._card_rect(idx)
        tag = self._card_tag(eid)
        cv = self._canvas
        fn = EntityCardGrid._font_name
        fs = EntityCardGrid._font_sub

        # border rectangle
        item["tag_border"] = cv.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill=colors["border"],
            outline="",
            tags=tag,
        )
        # inner background (1 px inset)
        item["tag_bg"] = cv.create_rectangle(
            x1 + 1,
            y1 + 1,
            x2 - 1,
            y2 - 1,
            fill=colors["bg"],
            outline="",
            tags=tag,
        )
        # name text — use smaller font for long names to keep them in the card
        name_font = fn if len(item["name"]) <= 18 else EntityCardGrid._font_name_sm
        item["tag_name"] = cv.create_text(
            x1 + 14,
            y1 + 20,
            text=item["name"],
            fill=colors["text"],
            font=name_font,
            anchor="w",
            width=cw - 28,
            tags=tag,
        )
        # status label (line 1 of sub)
        labels = _STATUS_LABEL[self.entity_type]
        status_lbl = labels.get(status, "В ожидании")
        if status != "idle":
            item["tag_sub1"] = cv.create_text(
                x1 + 14,
                y1 + 46,
                text=status_lbl,
                fill=colors["sub"],
                font=fs,
                anchor="w",
                tags=tag,
            )
            item["tag_sub2"] = cv.create_text(
                x1 + 14,
                y1 + 62,
                text=item["ts"],
                fill=colors["sub"],
                font=fs,
                anchor="w",
                tags=tag,
            )
        else:
            item["tag_sub1"] = cv.create_text(
                x1 + 14,
                y1 + 54,
                text=status_lbl,
                fill=colors["sub"],
                font=fs,
                anchor="w",
                tags=tag,
            )
            item["tag_sub2"] = None  # not used for idle

    def _repaint_card(self, eid: int) -> None:
        """Update colors/text of an existing card in-place (no recreate)."""
        item = self._items.get(eid)
        if not item:
            return
        status = item["status"]
        colors = _CARD_STATUS_COLORS.get(status, _CARD_STATUS_COLORS["idle"])
        labels = _STATUS_LABEL[self.entity_type]
        status_lbl = labels.get(status, "В ожидании")
        cv = self._canvas

        cv.itemconfigure(item["tag_border"], fill=colors["border"])
        cv.itemconfigure(item["tag_bg"], fill=colors["bg"])
        cv.itemconfigure(item["tag_name"], fill=colors["text"])

        # Find the card index to get its canvas coordinates
        try:
            idx = self._idx_to_eid.index(eid)
        except ValueError:
            return
        x1, y1, _x2, _y2 = self._card_rect(idx)

        if status != "idle":
            # Move sub1 (label) to the two-line position and update text
            cv.coords(item["tag_sub1"], x1 + 14, y1 + 46)
            cv.itemconfigure(item["tag_sub1"], text=status_lbl, fill=colors["sub"])
            # Create tag_sub2 (time) if it didn't exist (card was idle before)
            if item["tag_sub2"] is None:
                tag = self._card_tag(eid)
                item["tag_sub2"] = cv.create_text(
                    x1 + 14,
                    y1 + 62,
                    text=item["ts"],
                    fill=colors["sub"],
                    font=EntityCardGrid._font_sub,
                    anchor="w",
                    tags=tag,
                )
            else:
                cv.coords(item["tag_sub2"], x1 + 14, y1 + 62)
                cv.itemconfigure(
                    item["tag_sub2"],
                    text=item["ts"],
                    fill=colors["sub"],
                    state="normal",
                )
        else:
            # Move sub1 back to the single-line (centred) position
            cv.coords(item["tag_sub1"], x1 + 14, y1 + 54)
            cv.itemconfigure(item["tag_sub1"], text=status_lbl, fill=colors["sub"])
            if item["tag_sub2"] is not None:
                cv.itemconfigure(item["tag_sub2"], state="hidden")

    def _set_hover(self, eid: int, on: bool) -> None:
        """Highlight or un-highlight card border."""
        item = self._items.get(eid)
        if not item:
            return
        status = item["status"]
        colors = _CARD_STATUS_COLORS.get(status, _CARD_STATUS_COLORS["idle"])
        border = colors["text"] if on else colors["border"]
        self._canvas.itemconfigure(item["tag_border"], fill=border)

    def populate(self, rows) -> None:
        """Full rebuild: parse rows, draw all cards, set scrollregion."""
        self._canvas.delete("all")
        self._items.clear()
        self._order.clear()
        self._idx_to_eid.clear()
        self._hovered_eid = -1

        rows_list = [dict(r) for r in rows]
        rows_list.sort(key=lambda r: (r.get("number") or r.get("name") or "").lower())

        for row in rows_list:
            eid = row["id"]
            name = row.get("number") or row.get("name", "")
            status = row.get("status", "idle")
            raw_ts = row.get("updated") or row.get("created", "")
            ts = _fmt_timestamp(raw_ts)
            self._items[eid] = {
                "name": name,
                "status": status,
                "ts": ts,
                "tag_border": None,
                "tag_bg": None,
                "tag_name": None,
                "tag_sub1": None,
                "tag_sub2": None,
            }
            self._order.append(eid)

        self._idx_to_eid = list(self._order)  # already sorted

        # Draw all cards (one pass, no per-scroll work needed after this)
        for idx, eid in enumerate(self._order):
            self._draw_card(idx, eid)

        total_h = max(self._total_height(), 200)  # min height for scrollbar
        self._canvas.configure(
            scrollregion=(0, 0, max(self._canvas_w, 1), max(total_h, 1))
        )

    def row_count(self) -> int:
        return len(self._items)

    def _rebuild_after_delete(self) -> None:
        """Full redraw after a card is deleted — reuses in-memory data, no DB hit."""
        self._canvas.delete("all")
        self._order = sorted(
            self._items.keys(),
            key=lambda e: self._items[e]["name"].lower(),
        )
        self._idx_to_eid = list(self._order)
        self._hovered_eid = -1
        for idx, eid in enumerate(self._order):
            self._draw_card(idx, eid)
        total_h = self._total_height()
        self._canvas.configure(
            scrollregion=(0, 0, max(self._canvas_w, 1), max(total_h, 1))
        )

    def _on_configure(self, event) -> None:
        new_w = event.width
        if new_w == self._canvas_w:
            return
        self._canvas_w = new_w
        if not self._order:
            return
        # Card widths changed — redraw all cards at new positions
        yview = self._canvas.yview()
        self._canvas.delete("all")
        for idx, eid in enumerate(self._order):
            self._draw_card(idx, eid)
        total_h = max(self._total_height(), 200)  # min height for scrollbar
        self._canvas.configure(
            scrollregion=(0, 0, max(self._canvas_w, 1), max(total_h, 1))
        )
        self._canvas.yview_moveto(yview[0])

    def _on_mousewheel(self, event) -> None:
        # Global wheel handler - routes to canvas under cursor.
        # Route only to the canvas under the pointer
        w = event.widget
        while w is not None:
            if w is self._canvas:
                break
            w = getattr(w, "master", None)
        else:
            return

        delta = event.delta
        if abs(delta) >= 120:
            units = int(-delta / 120)
        else:
            units = -1 if delta > 0 else 1
        self._canvas.yview_scroll(units, "units")

    def _on_mousewheel_local(self, event) -> None:
        # Local fallback wheel handler for this canvas only.
        delta = event.delta
        if abs(delta) >= 120:
            units = int(-delta / 120)
        else:
            units = -1 if delta > 0 else 1
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
        new_status = "departed" if item["status"] == "arrived" else "arrived"
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
            if self.entity_type == "vehicle":
                self.db.delete_vehicle(eid)
            else:
                self.db.delete_commander(eid)
        except (DatabaseError, NotFoundError) as exc:
            messagebox.showerror("Ошибка", str(exc))
            return
        # Remove from in-memory store and redraw
        del self._items[eid]
        self._rebuild_after_delete()
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
