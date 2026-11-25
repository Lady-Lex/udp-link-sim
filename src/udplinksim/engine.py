"""Independent IPv4 UDP link-simulation engine (delay, jitter, loss, bounded queues)."""

from __future__ import annotations

import argparse
from array import array
import heapq
import itertools
import json
import os
import random
import selectors
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import ConfigValidationError, Rule, load_rules_csv, validate_rules
from .win_timer import HighResDeadlineWaiter, start_parent_exit_watcher

DEFAULT_MAX_RULE_PACKETS = 4096
DEFAULT_MAX_RULE_BYTES = 16 * 1024 * 1024  # 16 MiB per rule
DEFAULT_MAX_TOTAL_PACKETS = 32768
DEFAULT_MAX_TOTAL_BYTES = 128 * 1024 * 1024  # 128 MiB global cap
DEFAULT_STATS_INTERVAL_MS = 250
DEFAULT_SPIN_US = 500  # A/B validated: improves worst-route P99 from 1.40ms to 0.96ms at +5.5% 1-core CPU
DEFAULT_SOCKET_BUF_BYTES = 1 * 1024 * 1024  # 1 MiB best-effort OS UDP buffer
_INF_NS = (1 << 63) - 1


@dataclass
class EngineOptions:
    max_rule_packets: int = DEFAULT_MAX_RULE_PACKETS
    max_rule_bytes: int = DEFAULT_MAX_RULE_BYTES
    max_total_packets: int = DEFAULT_MAX_TOTAL_PACKETS
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES
    stats_interval_ms: int = DEFAULT_STATS_INTERVAL_MS
    spin_us: int = DEFAULT_SPIN_US
    force_timer_fallback: bool = False
    seed: int | None = None
    timing_out: str | None = None
    socket_buf_bytes: int = DEFAULT_SOCKET_BUF_BYTES


@dataclass
class RuleRuntime:
    index: int
    rule: Rule
    listener_key: tuple[str, int]
    sock: socket.socket
    loss_prob: float
    rx: int = 0
    tx: int = 0
    queued_packets: int = 0
    queued_bytes: int = 0
    loss_drops: int = 0
    overflow_drops: int = 0
    send_errors: int = 0
    discarded_on_stop: int = 0
    last_tx: int = 0
    tx_rate: float = 0.0
    lateness_ns: array | None = None


@dataclass
class ListenerRuntime:
    endpoint: tuple[str, int]
    sock: socket.socket
    exact_routes: dict[tuple[str, int], RuleRuntime] = field(default_factory=dict)
    wildcard_routes: dict[str, RuleRuntime] = field(default_factory=dict)
    unmatched_packets: int = 0
    last_unmatched_peer: str = ""
    last_unmatched_ts: float = 0.0
    wsa10054: int = 0
    recv_errors: int = 0


def _percentile_sorted(sorted_vals: list[int], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    idx = (pct / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _summarize_lateness_ns(samples: array) -> dict[str, Any]:
    if not samples:
        return {
            "count": 0,
            "min_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "p999_ms": 0.0,
            "max_ms": 0.0,
            "mean_ms": 0.0,
        }
    vals = sorted(samples)
    total = sum(vals)
    return {
        "count": len(vals),
        "min_ms": round(vals[0] / 1e6, 6),
        "p50_ms": round(_percentile_sorted(vals, 50.0) / 1e6, 6),
        "p95_ms": round(_percentile_sorted(vals, 95.0) / 1e6, 6),
        "p99_ms": round(_percentile_sorted(vals, 99.0) / 1e6, 6),
        "p999_ms": round(_percentile_sorted(vals, 99.9) / 1e6, 6),
        "max_ms": round(vals[-1] / 1e6, 6),
        "mean_ms": round((total / len(vals)) / 1e6, 6),
    }


class UdpEngine:
    """High-precision multi-route IPv4 UDP link simulator engine."""

    def __init__(
        self,
        rules: Sequence[Rule],
        options: EngineOptions | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.rules = validate_rules(rules, require_non_empty=True)
        self.options = options or EngineOptions()
        self._on_event = on_event

        self._rng = random.Random(self.options.seed)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._started = False
        self._stopped = False

        self._heap: list[tuple[int, int, int, bytes]] = []
        self._seq = itertools.count()
        self._armed_deadline_ns: int = _INF_NS
        self._global_queued_packets = 0
        self._global_queued_bytes = 0
        self._discarded_pending_total = 0

        self._selector: selectors.BaseSelector | None = None
        self._wake_rx_sock: socket.socket | None = None
        self._listeners: dict[tuple[str, int], ListenerRuntime] = {}
        self._rule_runtimes: list[RuleRuntime] = []
        self._waiter: HighResDeadlineWaiter | None = None

        self._rx_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None
        self._stats_thread: threading.Thread | None = None
        self._start_mono = 0.0
        self._last_stats_mono = 0.0

    @property
    def timer_mode(self) -> str:
        return self._waiter.timer_mode if self._waiter is not None else "uninitialized"

    @property
    def discarded_pending_total(self) -> int:
        return self._discarded_pending_total

    def start(self) -> None:
        if self._started:
            raise RuntimeError("Engine already started")
        self._stop_event.clear()
        self._stopped = False

        waiter = HighResDeadlineWaiter(
            spin_us=self.options.spin_us,
            force_fallback=self.options.force_timer_fallback,
        )
        sel = selectors.DefaultSelector()
        wake_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bound_sockets: list[socket.socket] = []

        try:
            wake_sock.bind(("127.0.0.1", 0))
            wake_sock.setblocking(False)
            sel.register(wake_sock, selectors.EVENT_READ, data=None)

            listeners: dict[tuple[str, int], ListenerRuntime] = {}
            rule_runtimes: list[RuleRuntime] = []
            record_timing = bool(self.options.timing_out)

            for idx, rule in enumerate(self.rules):
                ep = rule.listen_endpoint
                lr = listeners.get(ep)
                if lr is None:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    bound_sockets.append(sock)
                    if self.options.socket_buf_bytes > 0:
                        try:
                            sock.setsockopt(
                                socket.SOL_SOCKET,
                                socket.SO_RCVBUF,
                                self.options.socket_buf_bytes,
                            )
                            sock.setsockopt(
                                socket.SOL_SOCKET,
                                socket.SO_SNDBUF,
                                self.options.socket_buf_bytes,
                            )
                        except OSError:
                            pass
                    sock.bind(ep)
                    sock.setblocking(False)
                    lr = ListenerRuntime(endpoint=ep, sock=sock)
                    listeners[ep] = lr
                    sel.register(sock, selectors.EVENT_READ, data=lr)

                rr = RuleRuntime(
                    index=idx,
                    rule=rule,
                    listener_key=ep,
                    sock=lr.sock,
                    loss_prob=rule.loss_pct / 100.0,
                    lateness_ns=array("q") if record_timing else None,
                )
                rule_runtimes.append(rr)
                if rule.source_port == 0:
                    lr.wildcard_routes[rule.source_ip] = rr
                else:
                    lr.exact_routes[rule.source_endpoint] = rr

            self._waiter = waiter
            self._selector = sel
            self._wake_rx_sock = wake_sock
            self._listeners = listeners
            self._rule_runtimes = rule_runtimes
            self._start_mono = time.perf_counter()
            self._last_stats_mono = self._start_mono
            self._started = True

            self._tx_thread = threading.Thread(
                target=self._tx_loop, name="udplink-tx", daemon=False
            )
            self._rx_thread = threading.Thread(
                target=self._rx_loop, name="udplink-rx", daemon=False
            )
            self._tx_thread.start()
            self._rx_thread.start()

            if self._on_event is not None and self.options.stats_interval_ms > 0:
                self._stats_thread = threading.Thread(
                    target=self._stats_loop, name="udplink-stats", daemon=True
                )
                self._stats_thread.start()

            self._emit(
                {
                    "type": "ready",
                    "pid": os.getpid(),
                    "rule_count": len(self._rule_runtimes),
                    "listener_count": len(self._listeners),
                    "timer_mode": self.timer_mode,
                    "spin_us": self.options.spin_us,
                }
            )
        except Exception:
            for s in bound_sockets:
                try:
                    s.close()
                except OSError:
                    pass
            try:
                wake_sock.close()
            except OSError:
                pass
            try:
                sel.close()
            except Exception:
                pass
            waiter.close()
            raise

    def _wake_rx(self) -> None:
        ws = self._wake_rx_sock
        if ws is None:
            return
        try:
            addr = ws.getsockname()
            ws.sendto(b"\x00", addr)
        except OSError:
            pass

    def _rx_loop(self) -> None:
        sel = self._selector
        waiter = self._waiter
        assert sel is not None and waiter is not None

        max_rp = self.options.max_rule_packets
        max_rb = self.options.max_rule_bytes
        max_tp = self.options.max_total_packets
        max_tb = self.options.max_total_bytes
        rng = self._rng
        perf_ns = time.perf_counter_ns
        next_seq = self._seq.__next__
        heap = self._heap

        while not self._stop_event.is_set():
            try:
                events = sel.select(timeout=0.5)
            except OSError:
                if self._stop_event.is_set():
                    break
                continue
            if self._stop_event.is_set():
                break

            for key, _ in events:
                lr: ListenerRuntime | None = key.data
                sock: socket.socket = key.fileobj  # type: ignore[assignment]
                if lr is None:
                    # Drain wakeup socket
                    try:
                        while True:
                            sock.recvfrom(64)
                    except OSError:
                        pass
                    continue

                # Drain all pending datagrams on this listener socket
                while not self._stop_event.is_set():
                    try:
                        data, peer = sock.recvfrom(65535)
                    except BlockingIOError:
                        break
                    except ConnectionResetError as exc:
                        if getattr(exc, "winerror", None) == 10054:
                            with self._lock:
                                lr.wsa10054 += 1
                            continue
                        with self._lock:
                            lr.recv_errors += 1
                        break
                    except OSError as exc:
                        if self._stop_event.is_set():
                            break
                        if getattr(exc, "winerror", None) == 10054:
                            with self._lock:
                                lr.wsa10054 += 1
                            continue
                        if getattr(exc, "winerror", None) in (10035, 11):  # EWOULDBLOCK
                            break
                        with self._lock:
                            lr.recv_errors += 1
                        break

                    recv_ns = perf_ns()
                    rr = lr.exact_routes.get(peer)
                    if rr is None:
                        rr = lr.wildcard_routes.get(peer[0])
                    if rr is None:
                        with self._lock:
                            lr.unmatched_packets += 1
                            lr.last_unmatched_peer = f"{peer[0]}:{peer[1]}"
                            lr.last_unmatched_ts = time.time()
                        continue

                    # Independent Bernoulli loss before delay/queue
                    loss_prob = rr.loss_prob
                    if loss_prob > 0.0 and (loss_prob >= 1.0 or rng.random() < loss_prob):
                        with self._lock:
                            rr.rx += 1
                            rr.loss_drops += 1
                        continue

                    # Independent nonnegative clamped Gaussian delay
                    rule = rr.rule
                    if rule.sigma_ms > 0.0:
                        delay_ms = rng.gauss(rule.base_ms, rule.sigma_ms)
                        if delay_ms < 0.0:
                            delay_ms = 0.0
                    else:
                        delay_ms = rule.base_ms
                    deadline_ns = recv_ns + int(round(delay_ms * 1_000_000.0))
                    nbytes = len(data)

                    wake_tx = False
                    with self._lock:
                        rr.rx += 1
                        if (
                            rr.queued_packets + 1 > max_rp
                            or rr.queued_bytes + nbytes > max_rb
                            or self._global_queued_packets + 1 > max_tp
                            or self._global_queued_bytes + nbytes > max_tb
                        ):
                            rr.overflow_drops += 1
                            continue

                        heapq.heappush(heap, (deadline_ns, next_seq(), rr.index, data))
                        rr.queued_packets += 1
                        rr.queued_bytes += nbytes
                        self._global_queued_packets += 1
                        self._global_queued_bytes += nbytes
                        if deadline_ns < self._armed_deadline_ns:
                            wake_tx = True

                    if wake_tx:
                        waiter.wake()

    def _tx_loop(self) -> None:
        waiter = self._waiter
        assert waiter is not None
        heap = self._heap
        runtimes = self._rule_runtimes
        perf_ns = time.perf_counter_ns
        stop_is_set = self._stop_event.is_set

        while not stop_is_set():
            due_items: list[tuple[int, int, bytes]] = []
            next_deadline_ns: int | None = None

            with self._lock:
                if not heap:
                    self._armed_deadline_ns = _INF_NS
                else:
                    now_ns = perf_ns()
                    while heap and heap[0][0] <= now_ns:
                        d_ns, _seq, r_idx, payload = heapq.heappop(heap)
                        rr = runtimes[r_idx]
                        rr.queued_packets -= 1
                        rr.queued_bytes -= len(payload)
                        self._global_queued_packets -= 1
                        self._global_queued_bytes -= len(payload)
                        due_items.append((d_ns, r_idx, payload))
                    if heap:
                        next_deadline_ns = heap[0][0]
                        self._armed_deadline_ns = next_deadline_ns
                    else:
                        self._armed_deadline_ns = _INF_NS

            if due_items:
                for d_ns, r_idx, payload in due_items:
                    if stop_is_set():
                        # Count remaining popped-but-unsent due items as discarded on stop
                        with self._lock:
                            runtimes[r_idx].discarded_on_stop += 1
                            self._discarded_pending_total += 1
                        continue
                    rr = runtimes[r_idx]
                    send_call_ns = perf_ns()
                    try:
                        rr.sock.sendto(payload, rr.rule.target_endpoint)
                        sent_ok = True
                    except OSError:
                        sent_ok = False
                    with self._lock:
                        if sent_ok:
                            rr.tx += 1
                            if rr.lateness_ns is not None:
                                rr.lateness_ns.append(send_call_ns - d_ns)
                        else:
                            rr.send_errors += 1
                # Loop immediately to re-check heap before sleeping
                continue

            if next_deadline_ns is None:
                waiter.wait_indefinite()
            else:
                waiter.wait_until(next_deadline_ns, stop_check=stop_is_set)

    def _stats_loop(self) -> None:
        interval_s = max(0.05, self.options.stats_interval_ms / 1000.0)
        while not self._stop_event.wait(interval_s):
            self._emit({"type": "stats", **self.snapshot()})

    def snapshot(self) -> dict[str, Any]:
        """Return a thread-safe stats snapshot."""
        now = time.perf_counter()
        with self._lock:
            dt = max(1e-6, now - self._last_stats_mono)
            self._last_stats_mono = now
            rules_stats = []
            totals = {
                "rx": 0,
                "tx": 0,
                "tx_rate": 0.0,
                "queued_packets": self._global_queued_packets,
                "queued_bytes": self._global_queued_bytes,
                "loss_drops": 0,
                "overflow_drops": 0,
                "send_errors": 0,
                "discarded_on_stop": self._discarded_pending_total,
                "unmatched_packets": 0,
                "wsa10054": 0,
            }
            for rr in self._rule_runtimes:
                rate = (rr.tx - rr.last_tx) / dt
                rr.last_tx = rr.tx
                rr.tx_rate = rate
                totals["rx"] += rr.rx
                totals["tx"] += rr.tx
                totals["tx_rate"] += rate
                totals["loss_drops"] += rr.loss_drops
                totals["overflow_drops"] += rr.overflow_drops
                totals["send_errors"] += rr.send_errors
                rules_stats.append(
                    {
                        "index": rr.index,
                        "listen": f"{rr.rule.listen_ip}:{rr.rule.listen_port}",
                        "source": f"{rr.rule.source_ip}:{rr.rule.source_port}",
                        "target": f"{rr.rule.target_ip}:{rr.rule.target_port}",
                        "rx": rr.rx,
                        "tx": rr.tx,
                        "tx_rate": round(rate, 1),
                        "queued_packets": rr.queued_packets,
                        "queued_bytes": rr.queued_bytes,
                        "loss_drops": rr.loss_drops,
                        "overflow_drops": rr.overflow_drops,
                        "send_errors": rr.send_errors,
                        "discarded_on_stop": rr.discarded_on_stop,
                    }
                )
            listeners_stats = []
            for ep, lr in self._listeners.items():
                totals["unmatched_packets"] += lr.unmatched_packets
                totals["wsa10054"] += lr.wsa10054
                listeners_stats.append(
                    {
                        "listen": f"{ep[0]}:{ep[1]}",
                        "unmatched_packets": lr.unmatched_packets,
                        "last_unmatched_peer": lr.last_unmatched_peer,
                        "last_unmatched_ts": lr.last_unmatched_ts,
                        "wsa10054": lr.wsa10054,
                        "recv_errors": lr.recv_errors,
                    }
                )
            totals["tx_rate"] = round(totals["tx_rate"], 1)

        return {
            "uptime_s": round(max(0.0, now - self._start_mono), 2),
            "pid": os.getpid(),
            "timer_mode": self.timer_mode,
            "spin_us": self.options.spin_us,
            "totals": totals,
            "rules": rules_stats,
            "listeners": listeners_stats,
        }

    def reset_stats(self) -> None:
        with self._lock:
            for rr in self._rule_runtimes:
                rr.rx = 0
                rr.tx = 0
                rr.last_tx = 0
                rr.tx_rate = 0.0
                rr.loss_drops = 0
                rr.overflow_drops = 0
                rr.send_errors = 0
                rr.discarded_on_stop = 0
            for lr in self._listeners.values():
                lr.unmatched_packets = 0
                lr.last_unmatched_peer = ""
                lr.last_unmatched_ts = 0.0
                lr.wsa10054 = 0
                lr.recv_errors = 0
            self._discarded_pending_total = 0

    def _write_timing_report(self) -> None:
        if not self.options.timing_out:
            return
        all_samples = array("q")
        per_rule = []
        for rr in self._rule_runtimes:
            samples = rr.lateness_ns if rr.lateness_ns is not None else array("q")
            all_samples.extend(samples)
            summary = _summarize_lateness_ns(samples)
            per_rule.append(
                {
                    "index": rr.index,
                    "listen": f"{rr.rule.listen_ip}:{rr.rule.listen_port}",
                    "source": f"{rr.rule.source_ip}:{rr.rule.source_port}",
                    "target": f"{rr.rule.target_ip}:{rr.rule.target_port}",
                    "base_ms": rr.rule.base_ms,
                    "sigma_ms": rr.rule.sigma_ms,
                    "loss_pct": rr.rule.loss_pct,
                    "rx": rr.rx,
                    "tx": rr.tx,
                    "loss_drops": rr.loss_drops,
                    "overflow_drops": rr.overflow_drops,
                    "send_errors": rr.send_errors,
                    "discarded_on_stop": rr.discarded_on_stop,
                    "lateness": summary,
                }
            )
        report = {
            "timer_mode": self.timer_mode,
            "spin_us": self.options.spin_us,
            "discarded_pending": self._discarded_pending_total,
            "overall_lateness": _summarize_lateness_ns(all_samples),
            "per_rule": per_rule,
            "listeners": [
                {
                    "listen": f"{ep[0]}:{ep[1]}",
                    "unmatched_packets": lr.unmatched_packets,
                    "last_unmatched_peer": lr.last_unmatched_peer,
                    "wsa10054": lr.wsa10054,
                    "recv_errors": lr.recv_errors,
                }
                for ep, lr in self._listeners.items()
            ],
        }
        out_path = Path(self.options.timing_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    def stop(self) -> dict[str, Any]:
        """Stop RX & TX threads, discard pending packets (no stale sends), close all sockets."""
        if not self._started or self._stopped:
            return {"discarded_pending": self._discarded_pending_total}
        self._stopped = True
        self._stop_event.set()
        self._wake_rx()
        if self._waiter is not None:
            self._waiter.wake()

        if self._rx_thread is not None:
            self._rx_thread.join(timeout=5.0)
        if self._tx_thread is not None:
            self._tx_thread.join(timeout=5.0)
        if self._stats_thread is not None:
            self._stats_thread.join(timeout=2.0)

        # Count & discard all remaining pending packets safely after both worker threads stopped
        with self._lock:
            while self._heap:
                _d_ns, _seq, r_idx, payload = heapq.heappop(self._heap)
                rr = self._rule_runtimes[r_idx]
                rr.queued_packets = max(0, rr.queued_packets - 1)
                rr.queued_bytes = max(0, rr.queued_bytes - len(payload))
                rr.discarded_on_stop += 1
                self._global_queued_packets = max(0, self._global_queued_packets - 1)
                self._global_queued_bytes = max(0, self._global_queued_bytes - len(payload))
                self._discarded_pending_total += 1
            discarded = self._discarded_pending_total

        # Close all sockets and selector so bound ports are released immediately
        if self._selector is not None:
            try:
                self._selector.close()
            except Exception:
                pass
            self._selector = None
        if self._wake_rx_sock is not None:
            try:
                self._wake_rx_sock.close()
            except OSError:
                pass
            self._wake_rx_sock = None
        for lr in self._listeners.values():
            try:
                lr.sock.close()
            except OSError:
                pass
        if self._waiter is not None:
            self._waiter.close()

        self._write_timing_report()
        final_snap = self.snapshot()
        stopped_event = {
            "type": "stopped",
            "discarded_pending": discarded,
            "stats": final_snap,
        }
        self._emit(stopped_event)
        return stopped_event

    def _emit(self, payload: dict[str, Any]) -> None:
        if self._on_event is not None:
            try:
                self._on_event(payload)
            except Exception:
                pass


def _stdout_emitter_factory() -> Callable[[dict[str, Any]], None]:
    write_lock = threading.Lock()

    def _emit(payload: dict[str, Any]) -> None:
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        with write_lock:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except OSError:
                pass

    return _emit


def run_engine_cli(argv: Sequence[str]) -> int:
    """CLI entrypoint for independent engine subprocess (zero Qt imports)."""
    parser = argparse.ArgumentParser(prog="UdpLinkSim --engine")
    parser.add_argument("--config", required=True, help="Path to CSV rules file")
    parser.add_argument("--stats-ms", type=int, default=DEFAULT_STATS_INTERVAL_MS)
    parser.add_argument("--spin-us", type=int, default=DEFAULT_SPIN_US)
    parser.add_argument("--force-timer-fallback", action="store_true")
    parser.add_argument("--max-rule-packets", type=int, default=DEFAULT_MAX_RULE_PACKETS)
    parser.add_argument("--max-rule-bytes", type=int, default=DEFAULT_MAX_RULE_BYTES)
    parser.add_argument("--max-total-packets", type=int, default=DEFAULT_MAX_TOTAL_PACKETS)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--timing-out", type=str, default=None)
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--no-stdin-control", action="store_true")
    args = parser.parse_args(list(argv))

    emit = _stdout_emitter_factory()

    try:
        rules = load_rules_csv(args.config, require_non_empty=True)
    except (FileNotFoundError, ConfigValidationError, OSError) as exc:
        emit({"type": "error", "message": str(exc)})
        return 2

    options = EngineOptions(
        max_rule_packets=args.max_rule_packets,
        max_rule_bytes=args.max_rule_bytes,
        max_total_packets=args.max_total_packets,
        max_total_bytes=args.max_total_bytes,
        stats_interval_ms=args.stats_ms,
        spin_us=args.spin_us,
        force_timer_fallback=args.force_timer_fallback,
        seed=args.seed,
        timing_out=args.timing_out,
    )

    engine = UdpEngine(rules, options=options, on_event=emit)
    done = threading.Event()

    def _request_stop(*_args: object) -> None:
        done.set()

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    try:
        engine.start()
    except OSError as exc:
        emit({"type": "error", "message": f"UDP 端口绑定失败: {exc}"})
        return 3
    except Exception as exc:
        emit({"type": "error", "message": f"引擎启动失败: {exc}"})
        return 4

    if args.parent_pid > 0:
        start_parent_exit_watcher(args.parent_pid, _request_stop)

    if not args.no_stdin_control:
        def _stdin_loop() -> None:
            try:
                for line in sys.stdin:
                    cmd = line.strip().upper()
                    if cmd == "STOP":
                        done.set()
                        return
                    if cmd == "RESET_STATS":
                        engine.reset_stats()
                    elif cmd == "PING":
                        emit({"type": "pong", "pid": os.getpid()})
            except Exception:
                pass
            # Stdin EOF (parent exited or closed control pipe) -> shutdown cleanly
            done.set()

        t_in = threading.Thread(target=_stdin_loop, name="engine-stdin", daemon=True)
        t_in.start()

    try:
        while not done.is_set():
            done.wait(timeout=0.25)
    finally:
        engine.stop()

    return 0
