"""Verify packaged onefile UdpLinkSim.exe: startup timings, engine dispatch, and forced GUI kill."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil


def _alloc_ports(n: int) -> list[int]:
    socks = []
    ports = []
    try:
        for _ in range(n):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", 0))
            ports.append(s.getsockname()[1])
            socks.append(s)
    finally:
        for s in socks:
            s.close()
    return ports


def _can_bind_udp(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def measure_gui_startup(exe: Path, example_csv: Path, runs: int = 3) -> list[dict]:
    results = []
    for i in range(runs):
        t0 = time.perf_counter()
        proc = subprocess.run(
            [
                str(exe),
                "--config",
                str(example_csv),
                "--startup-probe",
                "--exit-after-ready",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        wall_ms = (time.perf_counter() - t0) * 1000.0
        if proc.returncode != 0:
            raise RuntimeError(
                f"GUI startup run {i+1} failed rc={proc.returncode}\n"
                f"stdout={proc.stdout}\nstderr={proc.stderr}"
            )
        gui_ready_ms = None
        for line in proc.stdout.splitlines():
            if line.startswith("GUI_READY_MS="):
                gui_ready_ms = float(line.split("=", 1)[1].strip())
        results.append(
            {
                "run": i + 1,
                "wall_total_ms": round(wall_ms, 2),
                "gui_ready_ms": round(gui_ready_ms, 2) if gui_ready_ms is not None else None,
                "stderr_lines": len([l for l in proc.stderr.splitlines() if l.strip()]),
            }
        )
    return results


def measure_engine_startup(exe: Path, runs: int = 3) -> list[dict]:
    results = []
    with tempfile.TemporaryDirectory() as td:
        for i in range(runs):
            p = _alloc_ports(1)[0]
            csv_path = Path(td) / f"eng_{i}.csv"
            csv_path.write_text(
                "listen_ip,listen_port,source_ip,source_port,target_ip,target_port,base_ms,sigma_ms,loss_pct\n"
                f"127.0.0.1,{p},127.0.0.1,21001,127.0.0.1,22001,10,0,0\n",
                encoding="utf-8",
            )
            t0 = time.perf_counter()
            proc = subprocess.Popen(
                [str(exe), "--engine", "--config", str(csv_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            try:
                assert proc.stdout is not None and proc.stdin is not None
                ready_line = proc.stdout.readline().strip()
                ready_ms = (time.perf_counter() - t0) * 1000.0
                if not ready_line:
                    err = proc.stderr.read() if proc.stderr else ""
                    raise RuntimeError(f"Engine failed to emit ready: {err}")
                info = json.loads(ready_line)
                assert info.get("type") == "ready", info
                proc.stdin.write("STOP\n")
                proc.stdin.flush()
                proc.stdin.close()
                proc.wait(timeout=10)
                results.append(
                    {
                        "run": i + 1,
                        "ready_ms": round(ready_ms, 2),
                        "timer_mode": info.get("timer_mode"),
                        "pid": info.get("pid"),
                    }
                )
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
    return results


def verify_forced_gui_exit(exe: Path) -> dict:
    """Launch real packaged GUI with --auto-start, verify packet forwarding,
    hard-kill GUI process, and verify child engine exits and releases UDP port.
    """
    listen_port, sender_port, receiver_port = _alloc_ports(3)
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "forced_kill.csv"
        csv_path.write_text(
            "listen_ip,listen_port,source_ip,source_port,target_ip,target_port,base_ms,sigma_ms,loss_pct\n"
            f"127.0.0.1,{listen_port},127.0.0.1,{sender_port},127.0.0.1,{receiver_port},5,0,0\n",
            encoding="utf-8",
        )
        gui_proc = subprocess.Popen(
            [str(exe), "--config", str(csv_path), "--auto-start"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        engine_pids: list[int] = []
        try:
            # Wait until listen_port is bound by the GUI's child engine
            deadline = time.perf_counter() + 20.0
            while time.perf_counter() < deadline:
                if not _can_bind_udp(listen_port):
                    break
                if gui_proc.poll() is not None:
                    err = gui_proc.stderr.read() if gui_proc.stderr else ""
                    raise RuntimeError(f"GUI exited prematurely: rc={gui_proc.returncode} {err}")
                time.sleep(0.1)
            if _can_bind_udp(listen_port):
                raise TimeoutError("Packaged GUI did not start engine / bind port within 20s")

            # Verify live UDP forwarding through the GUI-managed engine
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s_tx, socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM
            ) as s_rx:
                s_tx.bind(("127.0.0.1", sender_port))
                s_rx.bind(("127.0.0.1", receiver_port))
                s_rx.settimeout(3.0)
                s_tx.sendto(b"HELLO_FROZEN_EXE", ("127.0.0.1", listen_port))
                data, peer = s_rx.recvfrom(4096)
                assert data == b"HELLO_FROZEN_EXE"
                assert peer == ("127.0.0.1", listen_port)

            # Collect descendant PIDs (note PyInstaller onefile spawns bootloader -> payload -> engine)
            p_gui = psutil.Process(gui_proc.pid)
            children = p_gui.children(recursive=True)
            engine_pids = [c.pid for c in children]

            # Find the actual GUI process (child of bootloader in onefile) and kill it HARD!
            # In PyInstaller onefile, the outer process is the bootloader and its direct child is the GUI Python process,
            # whose child is the engine (--engine). Killing the GUI Python process simulates Task Manager "End Task" on the GUI window!
            gui_python_proc = None
            for c in p_gui.children(recursive=False):
                gui_python_proc = c
                break

            t_kill = time.perf_counter()
            if gui_python_proc is not None:
                gui_python_proc.kill()
            gui_proc.kill()
            gui_proc.wait(timeout=5.0)

            # Wait for port release and all engine descendants to terminate
            rel_deadline = time.perf_counter() + 5.0
            port_released = False
            all_dead = False
            while time.perf_counter() < rel_deadline:
                port_released = _can_bind_udp(listen_port)
                all_dead = all(not psutil.pid_exists(pid) for pid in engine_pids)
                if port_released and all_dead:
                    break
                time.sleep(0.05)
            release_ms = (time.perf_counter() - t_kill) * 1000.0

            if not port_released or not all_dead:
                alive = [pid for pid in engine_pids if psutil.pid_exists(pid)]
                raise AssertionError(
                    f"After forced GUI kill: port_released={port_released}, alive_descendants={alive}"
                )

            return {
                "forwarding_ok": True,
                "descendant_count_before_kill": len(engine_pids),
                "port_released": port_released,
                "all_descendants_exited": all_dead,
                "release_latency_ms": round(release_ms, 2),
            }
        finally:
            if gui_proc.poll() is None:
                gui_proc.kill()
                gui_proc.wait(timeout=5.0)
            for pid in engine_pids:
                if psutil.pid_exists(pid):
                    try:
                        psutil.Process(pid).kill()
                    except psutil.Error:
                        pass


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    exe = root / "dist" / "UdpLinkSim.exe"
    example_csv = root / "examples" / "loopback_4ports_8rules.csv"
    if not exe.is_file():
        print(f"ERROR: {exe} not found", file=sys.stderr)
        return 1

    size_mb = exe.stat().st_size / (1024 * 1024)
    gui_runs = measure_gui_startup(exe, example_csv, runs=3)
    eng_runs = measure_engine_startup(exe, runs=3)
    forced_exit = verify_forced_gui_exit(exe)

    summary = {
        "exe_size_mb": round(size_mb, 2),
        "gui_startup": gui_runs,
        "engine_startup": eng_runs,
        "forced_gui_exit": forced_exit,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
