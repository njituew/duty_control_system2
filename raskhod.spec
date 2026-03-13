# -*- mode: python ; coding: utf-8 -*-
# ============================================================
#  Файл сборки PyInstaller
# ============================================================

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

PROJECT_ROOT = Path(SPECPATH)

ct_datas = collect_data_files("customtkinter")

a = Analysis(
    scripts=[str(PROJECT_ROOT / "main.py")],

    pathex=[str(PROJECT_ROOT)],

    binaries=[],

    datas=ct_datas + [(str(PROJECT_ROOT / "icon.ico"), ".")],

    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.messagebox",
        "tkinter.simpledialog",
        "darkdetect",
        "packaging",
        "packaging.version",
        "packaging.specifiers",
        "packaging.requirements",
    ],

    hookspath=[],
    hooksconfig={},

    runtime_hooks=[],

    excludes=[
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PIL",
        "Pillow",
        "cv2",
        "PyQt5",
        "PyQt6",
        "wx",
        "gi",
        "test",
        "unittest",
        "pydoc",
        "doctest",
        "difflib",
        "ftplib",
        "imaplib",
        "poplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
        "lib2to3",
        "distutils",
        "setuptools",
        "pkg_resources",
        "email",
        "html.parser",
        "http.server",
        "multiprocessing",
        "concurrent",
        "asyncio",
    ],

    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,

    upx=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],

    exclude_binaries=True,

    name="Расход",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,

    upx=False,
    upx_exclude=[],

    console=False,
    disable_windowed_traceback=False,

    icon=str(PROJECT_ROOT / "icon.ico"),

    version_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Расход",
)
