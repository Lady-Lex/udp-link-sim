"""PySide6 Qt Quick/QML GUI bootstrapper with High-DPI and startup measurement."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from .. import APP_NAME, __version__
from .models import AppController


def _resolve_qml_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "udplinksim" / "gui" / "qml"
    return Path(__file__).resolve().parent / "qml"


def run_gui(argv: Sequence[str] | None = None) -> int:
    t0 = time.perf_counter()
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--config", default=None, help="Initial CSV configuration path")
    parser.add_argument(
        "--startup-probe",
        action="store_true",
        help="Print measured GUI ready latency in milliseconds",
    )
    parser.add_argument(
        "--exit-after-ready",
        action="store_true",
        help="Exit cleanly immediately after the main QML window is ready",
    )
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Automatically start engine after loading --config",
    )
    args, qt_args = parser.parse_known_args(list(argv or ()))

    # Use Basic / Fusion Qt Quick Controls style for crisp custom modern theming
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

    app = QGuiApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("UdpLinkSim")

    # Crisp Chinese UI typography on Windows High DPI
    font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)

    controller = AppController(initial_config=args.config)
    app.aboutToQuit.connect(controller.shutdown)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("appController", controller)

    qml_errors: list[str] = []

    def _on_warnings(warnings) -> None:
        for w in warnings:
            qml_errors.append(w.toString())

    engine.warnings.connect(_on_warnings)

    qml_main = _resolve_qml_dir() / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_main)))

    if not engine.rootObjects():
        sys.stderr.write("Failed to load QML UI:\n" + "\n".join(qml_errors) + "\n")
        controller.shutdown()
        return 1

    if args.auto_start and args.config:
        controller.applyAndRestart()

    if args.startup_probe or args.exit_after_ready:
        def _report_ready() -> None:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if args.startup_probe:
                print(f"GUI_READY_MS={elapsed_ms:.2f}", flush=True)
            if args.exit_after_ready:
                app.quit()

        QTimer.singleShot(0, _report_ready)

    rc = app.exec()
    controller.shutdown()
    return int(rc)
