"""Вкладки приложения: AccountingTab, HistoryTab, StatsTab."""

from tkinter import messagebox
from typing import ClassVar

import customtkinter as ctk

from camera_config import load_settings
from config import CTRL_RADIUS, C
from database import Database, DatabaseError, DuplicateError
from ui.components import EntityCardGrid, EventTreeview
from ui.dialogs import InputDialog


class _EntitySection(ctk.CTkFrame):
    """Панель сущности одного типа: тулбар, поиск и сетка карточек.

    Используется как половина AccountingTab (ТС слева, командиры справа).
    """

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
        self._build_counter()

        self._grid = EntityCardGrid(
            self,
            self.db,
            self.entity_type,
            on_changed=self._on_grid_changed,
        )
        self._grid.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def _build_toolbar(self, title: str, search_placeholder: str) -> None:
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        toolbar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            toolbar,
            text=title,
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=C["text"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self.refresh())
        ctk.CTkEntry(
            toolbar,
            textvariable=self._search_var,
            placeholder_text=search_placeholder,
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"],
            border_color=C["border"],
            height=32,
            corner_radius=CTRL_RADIUS,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 10))

        ctk.CTkButton(
            toolbar,
            text="＋  Добавить",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=C["accent"],
            hover_color=C["accent_h"],
            text_color=C["bg"],
            corner_radius=CTRL_RADIUS,
            height=32,
            command=self._on_add,
        ).grid(row=0, column=2, sticky="e")

    def _build_counter(self) -> None:
        self._counter_lbl = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color=C["subtext"],
        )
        self._counter_lbl.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 4))

    def refresh(self) -> None:
        rows = self.db.get_entities(self.entity_type, self._search_var.get().strip())
        self._grid.populate(rows)
        self._update_counter()

    def _on_grid_changed(self) -> None:
        self._update_counter()

    def _update_counter(self) -> None:
        self._counter_lbl.configure(text=f"Записей: {self._grid.row_count()}")

    def _on_add(self) -> None:
        dialog = InputDialog(self, title="Добавить", prompt=self.add_prompt)
        text = dialog.get_input()
        if text is None:
            return
        try:
            self.db.add_entity(self.entity_type, text)
            self.refresh()
        except DuplicateError:
            messagebox.showwarning("Дубликат", f"«{text}» уже существует.", parent=self)
        except (DatabaseError, ValueError) as e:
            messagebox.showerror("Ошибка", str(e), parent=self)


class AccountingTab(ctk.CTkFrame):
    """Двухколоночная вкладка учёта: ТС слева, командиры справа."""

    def __init__(self, master, db: Database, **kwargs):
        super().__init__(master, fg_color=C["bg"], **kwargs)
        self.db = db

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_columnconfigure(2, weight=1)

        self._build()

    def _build(self) -> None:
        self._section_vehicles = _EntitySection(
            self,
            db=self.db,
            entity_type="vehicle",
            title="ТС",
            add_prompt="Введите номер ТС:",
            search_placeholder="Поиск по номеру ТС...",
        )
        self._section_vehicles.grid(row=0, column=0, sticky="nsew")

        ctk.CTkFrame(self, fg_color=C["border"], width=1).grid(
            row=0, column=1, sticky="ns", padx=0
        )

        self._section_commanders = _EntitySection(
            self,
            db=self.db,
            entity_type="commander",
            title="Командование",
            add_prompt="Введите ФИО командира:",
            search_placeholder="Поиск по ФИО...",
        )
        self._section_commanders.grid(row=0, column=2, sticky="nsew")

    def refresh(self) -> None:
        self._section_vehicles.refresh()
        self._section_commanders.refresh()


class HistoryTab(ctk.CTkFrame):
    """Вкладка журнала событий с поиском и очисткой."""

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
            self, heading_color=C["subtext"], row_height=30
        )
        self._tree_widget.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _build_header(self) -> None:
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
            text="Обновить",
            font=ctk.CTkFont(size=12),
            fg_color=C["card"],
            hover_color=C["border"],
            text_color=C["text"],
            corner_radius=CTRL_RADIUS,
            height=34,
            command=self.refresh,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="Очистить",
            font=ctk.CTkFont(size=12),
            fg_color=C["card"],
            hover_color=C["danger_h"],
            text_color=C["red"],
            corner_radius=CTRL_RADIUS,
            height=34,
            command=self._on_clear,
        ).pack(side="left")

    def _build_search(self) -> None:
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self.refresh())
        ctk.CTkEntry(
            self,
            textvariable=self._search_var,
            placeholder_text="Поиск по имени или событию...",
            font=ctk.CTkFont(size=12),
            fg_color=C["surface"],
            border_color=C["border"],
            height=36,
            corner_radius=CTRL_RADIUS,
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

    def refresh(self) -> None:
        events = self.db.get_events(self._search_var.get().strip())
        self._tree_widget.populate(events)

    def _on_clear(self) -> None:
        if messagebox.askyesno(
            "Очистить историю", "Удалить всю историю событий?", parent=self
        ):
            try:
                self.db.clear_events()
            except DatabaseError as e:
                messagebox.showerror("Ошибка", str(e), parent=self)
            self.refresh()


class StatsTab(ctk.CTkFrame):
    """Вкладка агрегированной статистики и последних событий."""

    _STAT_CARDS: ClassVar[list[tuple[str, str, str]]] = [
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

        recent_panel = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=0)
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
            recent_panel, heading_color=C["subtext"], row_height=30
        )
        self._recent_tree.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _build_header(self) -> None:
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
            text="Обновить",
            font=ctk.CTkFont(size=12),
            fg_color=C["card"],
            hover_color=C["border"],
            text_color=C["text"],
            corner_radius=CTRL_RADIUS,
            height=34,
            command=self.refresh,
        ).grid(row=0, column=1, sticky="e")

    def _make_stat_card(
        self, parent, col: int, title: str, value: str, color: str
    ) -> None:
        frame = ctk.CTkFrame(
            parent,
            fg_color=C["card"],
            corner_radius=0,
            border_width=1,
            border_color=C["border"],
        )
        frame.grid(row=0, column=col, padx=6, pady=4, sticky="ew")
        # Равные веса колонок, чтобы карточки делили ширину поровну.
        parent.grid_columnconfigure(col, weight=1)

        ctk.CTkLabel(
            frame,
            text=value,
            font=ctk.CTkFont(family="Consolas", size=30, weight="bold"),
            text_color=color,
        ).pack(pady=(18, 2))

        ctk.CTkLabel(
            frame, text=title, font=ctk.CTkFont(size=11), text_color=C["subtext"]
        ).pack(pady=(0, 16))

    def refresh(self) -> None:
        for widget in self._stats_row.winfo_children():
            widget.destroy()

        stats = self.db.stats()
        for i, (title, key, color_key) in enumerate(self._STAT_CARDS):
            self._make_stat_card(
                self._stats_row, i, title, str(stats[key]), C[color_key]
            )

        self._recent_tree.populate(self.db.recent_activity(10))


class SettingsTab(ctk.CTkFrame):
    """Настройки подключения к камере: хост, учётные данные и кнопка подключения."""

    def __init__(self, master, app, **kwargs):
        super().__init__(master, fg_color=C["bg"], **kwargs)
        self._app = app
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build()
        self.refresh()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Настройки камеры",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=C["text"],
        ).grid(row=0, column=0, sticky="w")

        panel = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=0)
        panel.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        card = ctk.CTkFrame(
            panel,
            fg_color=C["card"],
            corner_radius=0,
            border_width=1,
            border_color=C["border"],
        )
        card.grid(row=0, column=0, sticky="new", padx=24, pady=(24, 12))
        card.grid_columnconfigure(1, weight=1)

        self._build_fields(card)

        self._status_lbl = ctk.CTkLabel(
            card,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=C["subtext"],
        )
        self._status_lbl.grid(
            row=4, column=0, columnspan=2, sticky="w", padx=24, pady=(0, 6)
        )

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=5, column=0, columnspan=2, sticky="ew", padx=24, pady=(0, 20))
        btn_row.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            btn_row,
            text="Подключиться",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=C["accent"],
            hover_color=C["accent_h"],
            text_color=C["bg"],
            corner_radius=CTRL_RADIUS,
            height=36,
            command=self._on_connect,
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))

        ctk.CTkButton(
            btn_row,
            text="Отключить",
            font=ctk.CTkFont(size=13),
            fg_color=C["card"],
            hover_color=C["danger_h"],
            text_color=C["red"],
            corner_radius=CTRL_RADIUS,
            height=36,
            command=self._on_disconnect,
        ).grid(row=0, column=1, sticky="w")

    def _build_fields(self, card: ctk.CTkFrame) -> None:
        field_opts = {
            "font": ctk.CTkFont(size=11),
            "text_color": C["subtext"],
        }

        ctk.CTkLabel(card, text="IP / адрес камеры", **field_opts).grid(
            row=0, column=0, sticky="w", padx=24, pady=(20, 4)
        )
        self._host_entry = ctk.CTkEntry(
            card,
            font=ctk.CTkFont(size=13),
            fg_color=C["surface"],
            border_color=C["border"],
            height=38,
            corner_radius=CTRL_RADIUS,
            placeholder_text="например 192.168.1.10",
        )
        self._host_entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=24)

        ctk.CTkLabel(card, text="Логин", **field_opts).grid(
            row=2, column=0, sticky="w", padx=24, pady=(14, 4)
        )
        self._user_entry = ctk.CTkEntry(
            card,
            font=ctk.CTkFont(size=13),
            fg_color=C["surface"],
            border_color=C["border"],
            height=38,
            corner_radius=CTRL_RADIUS,
        )
        self._user_entry.grid(row=3, column=0, sticky="ew", padx=(24, 12))

        ctk.CTkLabel(card, text="Пароль", **field_opts).grid(
            row=2, column=1, sticky="w", padx=12, pady=(14, 4)
        )
        self._password_entry = ctk.CTkEntry(
            card,
            font=ctk.CTkFont(size=13),
            fg_color=C["surface"],
            border_color=C["border"],
            height=38,
            corner_radius=CTRL_RADIUS,
            show="•",
        )
        self._password_entry.grid(row=3, column=1, sticky="ew", padx=(12, 24))

    def refresh(self) -> None:
        saved = load_settings()
        self._host_entry.delete(0, "end")
        self._host_entry.insert(0, saved.get("host", ""))
        self._user_entry.delete(0, "end")
        self._user_entry.insert(0, saved.get("user", ""))
        self._password_entry.delete(0, "end")
        self._password_entry.insert(0, saved.get("password", ""))
        self._update_status()

    def update_status(self) -> None:
        """Обновить только строку статуса (без перезаполнения полей)."""
        self._update_status()

    def _update_status(self) -> None:
        state = getattr(self._app, "_camera_state", "")
        host = getattr(self._app, "_camera_host", "")
        if state == "connected":
            self._status_lbl.configure(
                text=f"●  Подключено: {host}", text_color=C["green"]
            )
        elif state == "error":
            self._status_lbl.configure(
                text="✕  Ошибка подключения к камере", text_color=C["red"]
            )
        elif state == "connecting":
            self._status_lbl.configure(
                text=f"◐  Подключение к {host}...", text_color=C["yellow"]
            )
        else:
            self._status_lbl.configure(
                text="○  Не подключено",
                text_color=C["idle"],
            )

    def _on_connect(self) -> None:
        host = self._host_entry.get().strip()
        if not host:
            self._status_lbl.configure(
                text="Укажите адрес камеры.", text_color=C["red"]
            )
            return
        self._app.connect_camera(
            host,
            self._user_entry.get(),
            self._password_entry.get(),
        )
        self._update_status()

    def _on_disconnect(self) -> None:
        self._app.disconnect_camera()
        self._update_status()
