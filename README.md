Система контроля расхода лс и тс.

# Сборка приложения на Windows

## Окружение:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Сборка (.spec файл)

```bash
pip install pyinstaller
pyinstaller raskhod.spec
```

## Сборка в 1 файл (не рекомендуется)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "Расход" --icon "icon.ico" --add-data "venv\Lib\site-packages\customtkinter;customtkinter" main.py
```
