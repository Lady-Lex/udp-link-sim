# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile specification for UdpLinkSim (Windows x64)."""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
QML_DIR = SRC / "udplinksim" / "gui" / "qml"

EXCLUDES = [
    "tkinter",
    "unittest",
    "pydoc",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DAnimation",
    "PySide6.QtCharts",
    "PySide6.QtGraphs",
    "PySide6.QtDesigner",
    "PySide6.QtQuick3D",
    "PySide6.QtSql",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtTest",
    "PySide6.QtWebSockets",
    "PySide6.QtWebChannel",
    "PySide6.QtNfc",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtHttpServer",
    "PySide6.QtDataVisualization",
    "PySide6.QtTextToSpeech",
    "PySide6.QtSpatialAudio",
    "PySide6.QtOpenGLWidgets",
]

a = Analysis(
    [str(ROOT / "scripts" / "entry_app.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        (str(QML_DIR / "*.qml"), "udplinksim/gui/qml"),
    ],
    hiddenimports=[
        "udplinksim.engine",
        "udplinksim.config",
        "udplinksim.win_timer",
        "udplinksim.manager",
        "udplinksim.gui.app",
        "udplinksim.gui.models",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.QtQuickControls2",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

# Filter out heavy unused Qt DLLs/plugins if accidentally pulled in by wildcard hooks
DROP_BIN_SUBSTRINGS = (
    "qt6webengine",
    "qt6pdf",
    "qt6multimedia",
    "qt6quick3d",
    "qt6charts",
    "qt6graphs",
    "qt63d",
    "qt6designer",
    "qt6virtualkeyboard",
    "qt6location",
    "qt6bluetooth",
    "qt6sensors",
    "qt6serialport",
    "qt6sql",
    "qt6texttospeech",
    "qt6spatialaudio",
    "qt6httpserver",
    "qt6datavisualization",
    "qt6remoteobjects",
    "qt6scxml",
    "qt6statemachine",
    "qt6nfc",
    "qt6websockets",
    "qt6webchannel",
    "opengl32sw.dll",
    "d3dcompiler_47.dll",
)

def _keep_entry(entry):
    name = entry[0].lower().replace("\\", "/")
    for pat in DROP_BIN_SUBSTRINGS:
        if pat in name:
            return False
    return True

a.binaries = [b for b in a.binaries if _keep_entry(b)]
a.datas = [d for d in a.datas if _keep_entry(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="UdpLinkSim",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
