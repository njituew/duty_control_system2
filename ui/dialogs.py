"""Модальный диалог ввода."""

import customtkinter as ctk

from config import CTRL_RADIUS, C


class InputDialog(ctk.CTkToplevel):
    """Модальный диалог."""

    def __init__(self, parent, title: str, prompt: str):
        super().__init__(parent)
        self.title(title)
        self.geometry("380x190")
        self.resizable(False, False)
        self.configure(fg_color=C["surface"])
        self.grab_set()
        self._result: str | None = None

        self._build(prompt)
        self.wait_window()

    def _build(self, prompt: str) -> None:
        ctk.CTkLabel(
            self, text=prompt, font=ctk.CTkFont(size=13), text_color=C["text"]
        ).pack(pady=(20, 8), padx=24, anchor="w")

        self._entry = ctk.CTkEntry(
            self,
            font=ctk.CTkFont(size=13),
            fg_color=C["card"],
            border_color=C["border"],
            height=38,
            corner_radius=CTRL_RADIUS,
        )
        self._entry.pack(fill="x", padx=24)
        self._entry.bind("<Return>", self._confirm)
        self.after(50, self._set_focus)

        self._error_lbl = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=C["red"],
        )
        self._error_lbl.pack(pady=(4, 0), padx=24, anchor="w")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=10)

        ctk.CTkButton(
            btn_frame,
            text="Добавить",
            fg_color=C["accent"],
            hover_color=C["accent_h"],
            text_color=C["bg"],
            font=ctk.CTkFont(size=13),
            height=36,
            corner_radius=CTRL_RADIUS,
            command=self._confirm,
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="Отмена",
            fg_color=C["card"],
            hover_color=C["border"],
            text_color=C["subtext"],
            font=ctk.CTkFont(size=13),
            height=36,
            corner_radius=CTRL_RADIUS,
            command=self.destroy,
        ).pack(side="left", expand=True, fill="x")

    def _set_focus(self) -> None:
        self.lift()
        self.focus_force()
        self._entry.focus_set()

    def _confirm(self, _=None) -> None:
        """Проверить ввод и сохранить результат или показать ошибку."""
        text = self._entry.get().strip()
        if not text:
            self._error_lbl.configure(text="Поле не может быть пустым.")
            self._entry.configure(border_color=C["red"])
            self._entry.focus_set()
            return
        self._result = text
        self.destroy()

    def get_input(self) -> str | None:
        """Вернуть подтверждённый ввод или None, если диалог отменён."""
        return self._result
