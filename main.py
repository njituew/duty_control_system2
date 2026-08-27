from core.logging_setup import setup_logging
from ui.app import App

if __name__ == "__main__":
    setup_logging()
    app = App()
    app.mainloop()
