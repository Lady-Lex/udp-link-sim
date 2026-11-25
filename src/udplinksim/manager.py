"""Subprocess manager for the independent UDP engine with strict lifetime & port release."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import Rule, save_rules_csv
from .win_timer import IS_WINDOWS, KillOnCloseJob


def build_engine_command(
    config_path: str | os.PathLike[str],
    *,
    stats_ms: int = 250,
    spin_us: int = 500,
    parent_pid: int | None = None,
    extra_args: Sequence[str] = (),
) -> list[str]:
    """Build subprocess argv for frozen onefile EXE or source Python invocation."""
    if getattr(sys, "frozen", False):
        base = [sys.executable, "--engine"]
    else:
        base = [sys.executable, "-m", "udplinksim", "--engine"]
    cmd = [
        *base,
        "--config",
        str(config_path),
        "--stats-ms",
        str(stats_ms),
        "--spin-us",
        str(spin_us),
    ]
    if parent_pid:
        cmd.extend(["--parent-pid", str(parent_pid)])
    cmd.extend(extra_args)
    return cmd


class EngineProcessManager:
    """Manages an isolated engine child process with Win32 Job Object + clean restart."""

    def __init__(
        self,
        *,
        on_stats: Callable[[dict[str, Any]], None] | None = None,
        on_state: Callable[[str, str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        stats_ms: int = 250,
        spin_us: int = 500,
    ) -> None:
        self._on_stats = on_stats
        self._on_state = on_state
        self._on_log = on_log
        self.stats_ms = stats_ms
        self.spin_us = spin_us

        self._lock = threading.Lock()
        self._job: KillOnCloseJob | None = KillOnCloseJob() if IS_WINDOWS else None
        self._proc: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._temp_config_path: Path | None = None

        self._ready_event = threading.Event()
        self._stopped_event = threading.Event()
        self._startup_error: str | None = None
        self._ready_info: dict[str, Any] = {}
        self._last_discarded_pending: int = 0
        self._last_stats: dict[str, Any] = {}
        self._intentional_stop = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return int(self._proc.pid)
            return 0

    @property
    def last_discarded_pending(self) -> int:
        return self._last_discarded_pending

    @property
    def ready_info(self) -> dict[str, Any]:
        return dict(self._ready_info)

    def start_rules(
        self,
        rules: Sequence[Rule],
        *,
        timeout_s: float = 10.0,
        extra_args: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Write rules to a secure temp CSV and start the engine subprocess."""
        fd, tmp_name = tempfile.mkstemp(prefix="udplinksim_run_", suffix=".csv")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            save_rules_csv(tmp_path, rules, include_loss_column=True)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return self.start_csv(
            tmp_path,
            timeout_s=timeout_s,
            extra_args=extra_args,
            _temp_file=tmp_path,
        )

    def start_csv(
        self,
        config_path: str | os.PathLike[str],
        *,
        timeout_s: float = 10.0,
        extra_args: Sequence[str] = (),
        _temp_file: Path | None = None,
    ) -> dict[str, Any]:
        """Start engine subprocess for the given CSV path (stops any existing engine first)."""
        if self.is_running:
            self.stop()

        self._ready_event.clear()
        self._stopped_event.clear()
        self._startup_error = None
        self._ready_info = {}
        self._intentional_stop = False
        self._temp_config_path = _temp_file

        cmd = build_engine_command(
            config_path,
            stats_ms=self.stats_ms,
            spin_us=self.spin_us,
            parent_pid=os.getpid(),
            extra_args=extra_args,
        )

        creationflags = 0
        if IS_WINDOWS:
            creationflags = subprocess.CREATE_NO_WINDOW

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        if not getattr(sys, "frozen", False):
            # Ensure src/ is importable by the child python -m udplinksim
            src_dir = str(Path(__file__).resolve().parent.parent)
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                f"{src_dir}{os.pathsep}{existing}" if existing else src_dir
            )

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            env=env,
        )

        if self._job is not None:
            self._job.assign_pid(proc.pid)

        with self._lock:
            self._proc = proc

        self._reader_thread = threading.Thread(
            target=self._read_stdout,
            args=(proc,),
            name="engine-stdout-reader",
            daemon=True,
        )
        self._reader_thread.start()

        if not self._ready_event.wait(timeout=timeout_s):
            self.stop()
            raise TimeoutError(f"引擎在 {timeout_s:.1f}s 内未就绪")

        if self._startup_error is not None:
            err = self._startup_error
            self.stop()
            raise RuntimeError(err)

        self._notify_state("running", f"引擎运行中 (PID {proc.pid})")
        return dict(self._ready_info)

    def _read_stdout(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        try:
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    self._notify_log(f"[engine] {line}")
                    continue

                mtype = msg.get("type")
                if mtype == "ready":
                    self._ready_info = msg
                    self._ready_event.set()
                    self._notify_log(
                        f"引擎已启动: PID={msg.get('pid')} "
                        f"规则={msg.get('rule_count')} 监听={msg.get('listener_count')} "
                        f"定时器={msg.get('timer_mode')} spin={msg.get('spin_us')}us"
                    )
                elif mtype == "stats":
                    self._last_stats = msg
                    if self._on_stats is not None:
                        self._on_stats(msg)
                elif mtype == "stopped":
                    self._last_discarded_pending = int(msg.get("discarded_pending", 0))
                    if isinstance(msg.get("stats"), dict):
                        self._last_stats = msg["stats"]
                    self._stopped_event.set()
                elif mtype == "error":
                    self._startup_error = str(msg.get("message", "未知引擎错误"))
                    self._ready_event.set()
                    self._notify_log(f"引擎错误: {self._startup_error}")
        finally:
            rc = proc.wait()
            stderr_text = ""
            if proc.stderr is not None:
                try:
                    stderr_text = proc.stderr.read().strip()
                except Exception:
                    pass
            if not self._ready_event.is_set():
                self._startup_error = (
                    stderr_text or f"引擎进程异常退出 (exit={rc})"
                )
                self._ready_event.set()
            self._stopped_event.set()
            if not self._intentional_stop and rc != 0:
                detail = stderr_text or f"引擎意外退出 (exit={rc})"
                self._notify_log(detail)
                self._notify_state("error", detail)
            elif not self._intentional_stop:
                self._notify_state("stopped", "引擎已停止")

    def reset_stats(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None and proc.stdin is not None:
            try:
                proc.stdin.write("RESET_STATS\n")
                proc.stdin.flush()
            except OSError:
                pass

    def stop(self, timeout_s: float = 5.0) -> int:
        """Stop the engine gracefully (fallback terminate), wait for port release, return discarded count."""
        with self._lock:
            proc = self._proc
            self._intentional_stop = True

        discarded = 0
        if proc is not None:
            if proc.poll() is None and proc.stdin is not None:
                try:
                    proc.stdin.write("STOP\n")
                    proc.stdin.flush()
                except OSError:
                    pass
                try:
                    proc.stdin.close()
                except OSError:
                    pass

            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)

            if self._reader_thread is not None and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=2.0)
            discarded = self._last_discarded_pending

            with self._lock:
                self._proc = None

        if self._temp_config_path is not None:
            try:
                self._temp_config_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._temp_config_path = None

        self._notify_state("stopped", f"引擎已停止 (丢弃在途包: {discarded})")
        return discarded

    def restart_rules(
        self, rules: Sequence[Rule], *, timeout_s: float = 10.0
    ) -> tuple[int, dict[str, Any]]:
        """Apply updated rules by stopping old engine cleanly and starting a fresh one."""
        discarded = self.stop() if self.is_running else 0
        info = self.start_rules(rules, timeout_s=timeout_s)
        return discarded, info

    def close(self) -> None:
        self.stop()
        if self._job is not None:
            self._job.close()
            self._job = None

    def _notify_state(self, state: str, message: str) -> None:
        if self._on_state is not None:
            try:
                self._on_state(state, message)
            except Exception:
                pass

    def _notify_log(self, message: str) -> None:
        if self._on_log is not None:
            try:
                self._on_log(message)
            except Exception:
                pass
