Система контроля расхода лс и тс.

# Сборка приложения на Windows

## Сборка (.spec файл)

Окружение:

```bash
python -m venv venv
source venv/bin/activate    # macOS / Linux
venv\Scripts\activate       # Windows (cmd/PowerShell)
pip install -r requirements.txt
pip install pyinstaller
```

Сборка:

```bash
pyinstaller raskhod.spec
```

## Старая команда (не рекомендуется)

```bash
pyinstaller --onefile --windowed --name "Расход" --icon "icon.ico" --add-data ".venv\Lib\site-packages\customtkinter;customtkinter" main.py
```
