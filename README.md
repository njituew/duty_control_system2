Система контроля расхода лс и тс.

# Сборка приложения на Windows

Установка pyinstaller:
```bash
pip install pyinstaller
```

Команда для сборки приложения на Windows:
```bash
pyinstaller --onefile --windowed --name "RASKHOD" --icon "icon.ico" --add-data ".venv\Lib\site-packages\customtkinter;customtkinter" --add-data "icon.ico;." main.py
```
(случай когда окружение в папке `.venv`)

