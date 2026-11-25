"""Tests for engine-only dispatch before Qt imports, subprocess lifecycle, and forced GUI exit."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

from udplinksim.config import Rule
from udplinksim.manager import EngineProcessManager


def _alloc_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _can_bind_udp(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def test_engine_only_dispatch_does_not_import_qt(tmp_path):
    port = _alloc_port()
    csv_path = tmp_path / "r.csv"
    csv_path.write_text(
        "listen_ip,listen_port,source_ip,source_port,target_ip,target_port,base_ms,sigma_ms,loss_pct\n"
        f"127.0.0.1,{port},127.0.0.1,21001,127.0.0.1,22001,5,0,0\n",
        encoding="utf-8",
    )

    probe_code = (
        "import sys\n"
        "from udplinksim import cli\n"
        f"rc = cli.main(['--engine', '--config', r'{csv_path}'])\n"
        "qt_loaded = any(m.startswith('PySide6') or m.startswith('shiboken6') for m in sys.modules)\n"
        "print('QT_LOADED=' + str(qt_loaded))\n"
        "raise SystemExit(rc)\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    proc = subprocess.run(
        [sys.executable, "-c", probe_code],
        input="STOP\n",
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "QT_LOADED=False" in proc.stdout


def test_manager_stats_restart_and_port_release():
    p1, p2, s_port, t_port = [_alloc_port() for _ in range(4)]
    stats_events: list[dict] = []
    mgr = EngineProcessManager(
        on_stats=lambda s: stats_events.append(s),
        stats_ms=100,
    )
    try:
        r1 = [Rule("127.0.0.1", p1, "127.0.0.1", s_port, "127.0.0.1", t_port, 200.0, 0.0, 0.0)]
        info1 = mgr.start_rules(r1)
        assert mgr.is_running
        pid1 = info1["pid"]
        assert not _can_bind_udp(p1)  # Port is actively held by engine

        # Wait for at least one stats snapshot
        deadline = time.perf_counter() + 2.0
        while not stats_events and time.perf_counter() < deadline:
            time.sleep(0.05)
        assert len(stats_events) >= 1

        # Enqueue a 200ms packet then restart with p2
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.bind(("127.0.0.1", s_port))
            sender.sendto(b"PENDING", ("127.0.0.1", p1))
            time.sleep(0.03)

        r2 = [Rule("127.0.0.1", p2, "127.0.0.1", s_port, "127.0.0.1", t_port, 10.0, 0.0, 0.0)]
        discarded, info2 = mgr.restart_rules(r2)
        assert discarded >= 1
        assert info2["pid"] != pid1
        assert _can_bind_udp(p1)  # Old port cleanly released!
        assert not _can_bind_udp(p2)  # New port cleanly bound!
    finally:
        mgr.close()
    assert _can_bind_udp(p2)


def test_forced_parent_exit_kills_engine_and_releases_port():
    """Simulate Task Manager / TerminateProcess hard-kill of the GUI parent.
    Verify engine child dies automatically and bound UDP port is freed.
    """
    listen_port = _alloc_port()
    helper = (
        "import json, time\n"
        "from udplinksim.config import Rule\n"
        "from udplinksim.manager import EngineProcessManager\n"
        "mgr = EngineProcessManager(stats_ms=250)\n"
        f"info = mgr.start_rules([Rule('127.0.0.1', {listen_port}, '127.0.0.1', 21001, '127.0.0.1', 22001, 10, 0, 0)])\n"
        "print(json.dumps(info), flush=True)\n"
        "time.sleep(60)\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    parent = subprocess.Popen(
        [sys.executable, "-c", helper],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    engine_pid = 0
    try:
        assert parent.stdout is not None
        ready_line = parent.stdout.readline().strip()
        assert ready_line, parent.stderr.read() if parent.stderr else "no output"
        info = json.loads(ready_line)
        engine_pid = int(info["pid"])
        assert psutil.pid_exists(engine_pid)
        assert not _can_bind_udp(listen_port)

        # HARD KILL parent (TerminateProcess on Windows!)
        parent.kill()
        parent.wait(timeout=5.0)

        # Engine MUST terminate automatically and free listen_port quickly
        deadline = time.perf_counter() + 3.0
        while time.perf_counter() < deadline:
            if not psutil.pid_exists(engine_pid) and _can_bind_udp(listen_port):
                break
            time.sleep(0.05)

        assert not psutil.pid_exists(engine_pid), f"Engine PID {engine_pid} survived forced parent exit!"
        assert _can_bind_udp(listen_port), f"UDP port {listen_port} was not released after forced parent exit!"
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5.0)
        if engine_pid and psutil.pid_exists(engine_pid):
            try:
                psutil.Process(engine_pid).kill()
            except psutil.Error:
                pass
