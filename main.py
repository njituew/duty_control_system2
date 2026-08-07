"""Точка входа в приложение."""

import logging

from ui.app import App

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        force=True,
    )
    app = App()
    app.mainloop()
