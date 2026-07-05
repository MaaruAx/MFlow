# -*- mode: python ; coding: utf-8 -*-
#
# MFlow — PyInstaller spec (onedir build)
#
# Onedir instead of onefile: QtWebEngine ships its own child process
# (QtWebEngineProcess.exe) plus Chromium resources (icudtl.dat, *.pak,
# locales/). Onefile would re-extract all of that to a temp folder on every
# launch — slower startup, and a self-extracting exe pattern that some
# antivirus/EDR flags. Onedir keeps everything in place on disk, which is
# also what we want: this folder gets zipped as-is and uploaded to R2, then
# the Inno Setup installer downloads + extracts it verbatim.
#
# No UPX (per project decision — UPX is not used for this build).

import os

block_cipher = None

# This spec now lives in packaging/, one level below the project root
# (where main.py, core/, ui/, presets/, etc. actually are).
PACKAGING_DIR = os.path.abspath(os.path.dirname(SPEC)) if 'SPEC' in globals() else os.getcwd()
PROJECT_ROOT = os.path.dirname(PACKAGING_DIR)
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, 'main.py')
ICON_FILE = os.path.join(PROJECT_ROOT, 'MFlow.ico')

# ── Data files bundled next to the executable ────────────────────────────────
# (source, dest_subfolder) — dest_subfolder mirrors the source-tree layout
# expected by core/platform_config.py's `_resource()`-style lookups.
datas = [
    ('ui/app.html',                    'ui'),
    ('ui/dock.html',                   'ui'),
    ('ui/Monaspace_Neon_Var.woff2',    'ui'),
    ('presets/*.json',                 'presets'),
    ('themes/*.json',                  'themes'),
    ('language/*.json',                'language'),
    ('MFlow.ico',                      '.'),
]

# Expand glob patterns manually (PyInstaller's Analysis datas doesn't glob
# by itself in every version — safer to expand here). All relative to
# PROJECT_ROOT since this spec sits one folder below it now.
import glob
expanded_datas = []
for src_pattern, dest in datas:
    matches = glob.glob(os.path.join(PROJECT_ROOT, src_pattern))
    if matches:
        for m in matches:
            expanded_datas.append((m, dest))
    else:
        # Non-glob single file entries (e.g. MFlow.ico) — keep as-is if it exists
        direct = os.path.join(PROJECT_ROOT, src_pattern)
        if os.path.isfile(direct):
            expanded_datas.append((direct, dest))

# ── Modules PyInstaller must NOT bundle ──────────────────────────────────────
# Only QtCore, QtGui, QtWidgets, QtWebChannel, QtWebEngineCore and
# QtWebEngineWidgets are actually imported anywhere in this codebase
# (verified via grep across the whole source tree).
excludes = [
    # Unused Qt modules
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D',
    'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
    'PySide6.QtBluetooth', 'PySide6.QtSerialPort', 'PySide6.QtSensors',
    'PySide6.QtPositioning', 'PySide6.QtNfc', 'PySide6.QtSql',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtCharts',
    'PySide6.QtDataVisualization', 'PySide6.QtRemoteObjects',
    'PySide6.QtNetworkAuth', 'PySide6.QtHttpServer',
    'PySide6.QtDesigner', 'PySide6.QtUiTools',
    'PySide6.QtTest', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
    'PySide6.QtStateMachine', 'PySide6.QtSvgWidgets',
    'PySide6.scripts',
    # Stdlib not needed at runtime
    'tkinter', 'unittest', 'pydoc_data', 'test', 'lib2to3',
]

# ── Local packages that use implicit namespace-package imports ──────────────
# core/ and ui/ have no __init__.py; PyInstaller's static analysis follows
# the `from core.x import y` / `from ui.x import y` statements fine via AST,
# but we list them explicitly as a safety net in case any import is
# constructed dynamically somewhere down the line.
hiddenimports = [
    'core.platform_config',
    'core.preset_manager',
    'core.curve_engine',
    'core.resolve_connection',
    'ui.backend',
]

a = Analysis(
    [MAIN_SCRIPT],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=expanded_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MFlow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MFlow',
)
