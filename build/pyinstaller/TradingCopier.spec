# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Trading Copier (Windows x64, onedir).

Build from repo root:
    pyinstaller build/pyinstaller/TradingCopier.spec --distpath dist --workpath build/pyi --clean -y
"""
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # schema.sql is loaded at runtime via __file__
        (os.path.join(ROOT, "app", "database", "schema.sql"),
         os.path.join("app", "database")),
    ],
    hiddenimports=[
        "MetaTrader5",
        "app.workers.worker_main",
        "app.workers.mt5_worker",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy.random._examples",
        "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TradingCopier",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TradingCopier",
)
