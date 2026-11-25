# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['点巡.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('Mondrian.ico', 'assets')],
    hiddenimports=['pyWinhook.cpyHook', 'win32timezone', 'pyautogui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # These optional scientific packages are installed on the build machine,
    # but are not used by the workbench or its Qt widgets.
    excludes=['numpy', 'pandas', 'scipy', 'matplotlib', 'IPython', 'pytest', 'PyQt5', 'PyQt6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='点巡',
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['Mondrian.ico'],
)
