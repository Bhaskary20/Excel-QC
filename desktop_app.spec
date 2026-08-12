# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the desktop QC app.

    pyinstaller desktop_app.spec

Bundles the two files the app reads by relative path at runtime
(template/Format.xlsx, config/default.yaml) plus CustomTkinter's own theme
JSON files, which it loads by path relative to its own package directory --
easy to miss since nothing imports them by name, so PyInstaller's static
analysis can't find them on its own.
"""

from PyInstaller.utils.hooks import collect_data_files

datas = [
    ("template/Format.xlsx", "template"),
    ("config/default.yaml", "config"),
]
datas += collect_data_files("customtkinter")

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Toll Plaza Response QC',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
