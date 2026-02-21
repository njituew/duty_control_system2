"""Модальные диалоги."""

import customtkinter as ctk
from config import C


class InputDialog(ctk.CTkToplevel):
    """Модальный диалог ввода текста."""

    def __init__(self, parent, title: str, prompt: str):
        super().__init__(parent)
        self.title(title)
        self.geometry("380x160")
        self.resizable(False, False)
        self.configure(fg_color=C["surface"])
        self.grab_set()
        self._result: str | None = None

        self._build(prompt)
        self.wait_window()

    def _build(self, prompt: str):
        ctk.CTkLabel(
            self, text=prompt, font=ctk.CTkFont(size=13), text_color=C["text"]
        ).pack(pady=(20, 8), padx=24, anchor="w")

        self._entry = ctk.CTkEntry(
            self,
            font=ctk.CTkFont(size=13),
            fg_color=C["card"],
            border_color=C["accent"],
            height=38,
            corner_radius=8,
        )
        self._entry.pack(fill="x", padx=24)
        self._entry.bind("<Return>", self._confirm)
        self.after(50, self._set_focus)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=14)

        ctk.CTkButton(
            btn_frame,
            text="Добавить",
            fg_color=C["accent"],
            hover_color=C["accent_h"],
            font=ctk.CTkFont(size=13),
            height=36,
            corner_radius=8,
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
            corner_radius=8,
            command=self.destroy,
        ).pack(side="left", expand=True, fill="x")

    def _set_focus(self):
        self.lift()
        self.focus_force()
        self._entry.focus_set()

    def _confirm(self, _=None):
        self._result = self._entry.get().strip()
        self.destroy()

    def get_input(self) -> str | None:
        return self._result
