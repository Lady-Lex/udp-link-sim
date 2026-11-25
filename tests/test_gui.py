"""Tests for PySide6 Qt Quick/QML GUI controller and Main.qml loading."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from udplinksim.gui.models import AppController


def _alloc_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_app_controller_crud_csv_theme_and_apply(tmp_path):
    app = QGuiApplication.instance() or QGuiApplication([])
    assert app is not None

    ctrl = AppController()
    try:
        assert ctrl.rulesModel.count == 0
        assert not ctrl.isValid

        # Theme toggle
        assert ctrl.darkMode is False
        ctrl.toggleTheme()
        assert ctrl.darkMode is True

        # Add, edit, duplicate, delete
        ctrl.addRule()
        assert ctrl.rulesModel.count == 1
        assert ctrl.selectedIndex == 0
        assert ctrl.hasUnsavedChanges is True
        assert ctrl.isValid is True

        p_listen, p_src, p_dst = _alloc_port(), _alloc_port(), _alloc_port()
        ok = ctrl.updateRule(
            0,
            "127.0.0.1", str(p_listen),
            "127.0.0.1", str(p_src),
            "127.0.0.1", str(p_dst),
            "15", "2.5", "5",
        )
        assert ok is True

        # Duplicate & delete
        ctrl.duplicateRule(0)
        assert ctrl.rulesModel.count == 2
        ctrl.deleteRule(1)
        assert ctrl.rulesModel.count == 1

        # Save & re-import
        csv_path = tmp_path / "gui_saved.csv"
        assert ctrl.saveCsvAs(str(csv_path)) is True
        assert ctrl.hasUnsavedChanges is False
        assert Path(ctrl.configPath) == csv_path.resolve()

        # Apply & start engine
        assert ctrl.applyAndRestart() is True
        assert ctrl.engineRunning is True
        assert ctrl.hasPendingApply is False

        # Edit while running -> pendingApply becomes True
        assert ctrl.updateRule(
            0,
            "127.0.0.1", str(p_listen),
            "127.0.0.1", str(p_src),
            "127.0.0.1", str(p_dst),
            "25", "0", "0",
        )
        assert ctrl.hasPendingApply is True

        # Apply restarts cleanly
        assert ctrl.applyAndRestart() is True
        assert ctrl.hasPendingApply is False

        ctrl.stopEngine()
        assert ctrl.engineRunning is False
    finally:
        ctrl.shutdown()


def test_qml_main_loads_cleanly_in_subprocess():
    """Run real GUI with --startup-probe --exit-after-ready to verify zero QML errors."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    example_csv = Path(__file__).resolve().parent.parent / "examples" / "loopback_4ports_8rules.csv"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "udplinksim",
            "--config",
            str(example_csv),
            "--startup-probe",
            "--exit-after-ready",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}\nstdout={proc.stdout}"
    assert "GUI_READY_MS=" in proc.stdout
    assert "Failed to load QML" not in proc.stderr
