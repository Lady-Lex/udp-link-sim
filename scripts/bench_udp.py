"""UdpLinkSim benchmark and soak harness: A/B timer spin, short bench, burst+GUI, and 30-min soak."""

from __future__ import annotations

import argparse
from array import array
import json
import os
import platform
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import psutil

# Packet format: magic(4B) + dir_id(1B) + flags(1B) + seq(4B) + send_ns(8B) + payload_pad
_HDR_FMT = "!4sBBIQ"
_HDR_SIZE = struct.calcsize(_HDR_FMT)
_MAGIC = b"ULSM"
_FLAG_STEADY = 0
_FLAG_BURST = 1


def _alloc_ports(count: int) -> list[int]:
    socks = []
    ports = []
    try:
        for _ in range(count):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", 0))
            ports.append(s.getsockname()[1])
            socks.append(s)
    finally:
        for s in socks:
            s.close()
    return ports


def _percentile(sorted_vals: list[int], pct: float) -> float:
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


def _summarize_ns(samples: array) -> dict[str, Any]:
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
    return {
        "count": len(vals),
        "min_ms": round(vals[0] / 1e6, 4),
        "p50_ms": round(_percentile(vals, 50.0) / 1e6, 4),
        "p95_ms": round(_percentile(vals, 95.0) / 1e6, 4),
        "p99_ms": round(_percentile(vals, 99.0) / 1e6, 4),
        "p999_ms": round(_percentile(vals, 99.9) / 1e6, 4),
        "max_ms": round(vals[-1] / 1e6, 4),
        "mean_ms": round((sum(vals) / len(vals)) / 1e6, 4),
    }


def collect_sanitized_vm_info() -> dict[str, Any]:
    mem_gb = round(psutil.virtual_memory().total / (1024**3), 2)
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "arch": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "total_ram_gb": mem_gb,
        "perf_counter_res_ns": round(time.get_clock_info("perf_counter").resolution * 1e9, 1),
        "environment": "Windows 10 VM (Proxmox QEMU/EDK II)",
    }


def run_single_benchmark(
    *,
    label: str,
    duration_s: float,
    base_ms: float = 20.0,
    sigma_ms: float = 0.0,
    loss_pct: float = 0.0,
    pps_per_dir: float = 100.0,
    payload_bytes: int = 64,
    spin_us: int = 0,
    force_timer_fallback: bool = False,
    burst_interval_s: float = 0.0,
    burst_count: int = 200,
    with_gui: bool = False,
    exe_path: Path | None = None,
) -> dict[str, Any]:
    """Run an independent-endpoint 4-port / 8-direction UDP benchmark against the engine."""
    listen_ports = _alloc_ports(4)
    pad_len = max(0, payload_bytes - _HDR_SIZE)
    pad_bytes = bytes((i & 0xFF) for i in range(pad_len))

    with tempfile.TemporaryDirectory() as td, ExitStack() as stack:
        td_path = Path(td)
        a_socks = []
        b_socks = []
        for _ in range(4):
            sa = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            sb = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            for s in (sa, sb):
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2 * 1024 * 1024)
                except OSError:
                    pass
                s.bind(("127.0.0.1", 0))
            a_socks.append(sa)
            b_socks.append(sb)

        # Build 4 shared sockets / 8 rules CSV
        csv_lines = [
            "listen_ip,listen_port,source_ip,source_port,target_ip,target_port,base_ms,sigma_ms,loss_pct"
        ]
        # dir 0..7 mapping: (sender_sock, receiver_sock, listen_port)
        directions: list[tuple[socket.socket, socket.socket, int]] = []
        for i in range(4):
            lp = listen_ports[i]
            ap = a_socks[i].getsockname()[1]
            bp = b_socks[i].getsockname()[1]
            csv_lines.append(f"127.0.0.1,{lp},127.0.0.1,{ap},127.0.0.1,{bp},{base_ms},{sigma_ms},{loss_pct}")
            directions.append((a_socks[i], b_socks[i], lp))
            csv_lines.append(f"127.0.0.1,{lp},127.0.0.1,{bp},127.0.0.1,{ap},{base_ms},{sigma_ms},{loss_pct}")
            directions.append((b_socks[i], a_socks[i], lp))

        csv_path = td_path / "bench_routes.csv"
        csv_path.write_text("\n".join(csv_lines) + "\n", encoding="utf-8")
        timing_out = td_path / "engine_timing.json"

        # Start engine subprocess
        if exe_path is not None:
            cmd = [str(exe_path), "--engine"]
        else:
            cmd = [sys.executable, "-m", "udplinksim", "--engine"]
        cmd.extend(
            [
                "--config",
                str(csv_path),
                "--stats-ms",
                "250",
                "--spin-us",
                str(spin_us),
                "--timing-out",
                str(timing_out),
                "--parent-pid",
                str(os.getpid()),
            ]
        )
        if force_timer_fallback:
            cmd.append("--force-timer-fallback")

        env = os.environ.copy()
        if exe_path is None:
            src_dir = str(Path(__file__).resolve().parent.parent / "src")
            env["PYTHONPATH"] = src_dir

        eng_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
        )

        # Optional concurrent GUI process (to test GUI activity alongside engine)
        gui_proc: subprocess.Popen | None = None
        if with_gui:
            gui_csv = td_path / "gui_activity.csv"
            # Separate ports so GUI runs its own idle/live window without colliding on listen_ports
            gui_lp = _alloc_ports(1)[0]
            gui_csv.write_text(
                "listen_ip,listen_port,source_ip,source_port,target_ip,target_port,base_ms,sigma_ms,loss_pct\n"
                f"127.0.0.1,{gui_lp},127.0.0.1,25001,127.0.0.1,25002,20,0,0\n",
                encoding="utf-8",
            )
            gui_cmd = (
                [str(exe_path), "--config", str(gui_csv), "--auto-start"]
                if exe_path is not None
                else [sys.executable, "-m", "udplinksim", "--config", str(gui_csv), "--auto-start"]
            )
            gui_proc = subprocess.Popen(
                gui_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )

        ready_info: dict[str, Any] = {}
        stats_count = 0
        stop_reader = threading.Event()

        def _drain_stdout() -> None:
            nonlocal stats_count
            assert eng_proc.stdout is not None
            for line in eng_proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if msg.get("type") == "stats":
                        stats_count += 1
                except json.JSONDecodeError:
                    pass

        try:
            assert eng_proc.stdout is not None and eng_proc.stdin is not None
            ready_line = eng_proc.stdout.readline().strip()
            if not ready_line:
                err = eng_proc.stderr.read() if eng_proc.stderr else ""
                raise RuntimeError(f"Engine failed to start: {err}")
            ready_info = json.loads(ready_line)
            if ready_info.get("type") != "ready":
                raise RuntimeError(f"Unexpected ready message: {ready_info}")

            t_out = threading.Thread(target=_drain_stdout, daemon=True)
            t_out.start()

            # Wait briefly if GUI was launched so it's live during measurement
            if gui_proc is not None:
                time.sleep(1.5)

            # Per-direction receiver metrics
            recv_lat_ns = [array("q") for _ in range(8)]
            burst_lat_ns = [array("q") for _ in range(8)]
            sent_steady = [0] * 8
            sent_burst = [0] * 8
            recv_steady = [0] * 8
            recv_burst = [0] * 8
            bad_src_port = [0] * 8
            bad_payload = [0] * 8
            out_of_order = [0] * 8
            last_seq = [-1] * 8
            dup_count = [0] * 8
            seen_seq_max = [-1] * 8

            stop_rx = threading.Event()

            # Dedicated receiver thread per socket (8 sockets -> 8 receiver threads)
            # Map each receiver socket to the direction ID whose target is that socket
            def _rx_worker(dir_id: int, r_sock: socket.socket, expected_lp: int) -> None:
                r_sock.settimeout(0.2)
                lat_arr = recv_lat_ns[dir_id]
                blat_arr = burst_lat_ns[dir_id]
                perf_ns = time.perf_counter_ns
                while not stop_rx.is_set():
                    try:
                        data, peer = r_sock.recvfrom(65535)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    rx_ns = perf_ns()
                    if peer[1] != expected_lp:
                        bad_src_port[dir_id] += 1
                    if len(data) != payload_bytes or data[:4] != _MAGIC or data[_HDR_SIZE:] != pad_bytes:
                        bad_payload[dir_id] += 1
                        continue
                    _m, d_id, flags, seq, send_ns = struct.unpack_from(_HDR_FMT, data, 0)
                    if d_id != dir_id:
                        bad_payload[dir_id] += 1
                        continue
                    e2e_ns = rx_ns - send_ns
                    if flags == _FLAG_BURST:
                        recv_burst[dir_id] += 1
                        blat_arr.append(e2e_ns)
                    else:
                        recv_steady[dir_id] += 1
                        lat_arr.append(e2e_ns)
                        if seq <= last_seq[dir_id]:
                            if seq == last_seq[dir_id]:
                                dup_count[dir_id] += 1
                            else:
                                out_of_order[dir_id] += 1
                        last_seq[dir_id] = seq
                        if seq > seen_seq_max[dir_id]:
                            seen_seq_max[dir_id] = seq

            rx_threads = []
            for d_id, (_s, r_sock, lp) in enumerate(directions):
                t = threading.Thread(
                    target=_rx_worker, args=(d_id, r_sock, lp), name=f"rx-{d_id}", daemon=True
                )
                t.start()
                rx_threads.append(t)

            # CPU & RSS monitor on engine process (and GUI if active)
            eng_ps = psutil.Process(ready_info["pid"])
            eng_ps.cpu_percent(interval=None)
            eng_cpu_samples: list[float] = []
            eng_rss_mb_samples: list[float] = []
            gui_cpu_samples: list[float] = []

            stop_mon = threading.Event()

            def _mon_worker() -> None:
                gui_ps_list: list[psutil.Process] = []
                if gui_proc is not None and gui_proc.poll() is None:
                    try:
                        gp = psutil.Process(gui_proc.pid)
                        gui_ps_list = [gp, *gp.children(recursive=True)]
                        for p in gui_ps_list:
                            p.cpu_percent(interval=None)
                    except psutil.Error:
                        gui_ps_list = []
                while not stop_mon.wait(1.0):
                    try:
                        eng_cpu_samples.append(eng_ps.cpu_percent(interval=None))
                        eng_rss_mb_samples.append(eng_ps.memory_info().rss / (1024 * 1024))
                    except psutil.Error:
                        pass
                    if gui_ps_list:
                        gsum = 0.0
                        for p in gui_ps_list:
                            try:
                                gsum += p.cpu_percent(interval=None)
                            except psutil.Error:
                                pass
                        gui_cpu_samples.append(gsum)

            t_mon = threading.Thread(target=_mon_worker, daemon=True)
            t_mon.start()

            # Paced sender loop across all 8 directions (staggered evenly across each 10ms slot for 100pps/dir)
            # Using high-res waitable timer in the generator too so generator pacing is clean!
            from udplinksim.win_timer import HighResDeadlineWaiter

            gen_waiter = HighResDeadlineWaiter(spin_us=0)
            try:
                slot_ns = int(round(1e9 / (pps_per_dir * 8.0)))  # 1.25 ms between sends for 800 pps total
                total_steady_sends = int(round(duration_s * pps_per_dir * 8.0))
                t_start_ns = time.perf_counter_ns()
                next_burst_ns = (
                    t_start_ns + int(burst_interval_s * 1e9)
                    if burst_interval_s > 0
                    else (1 << 63) - 1
                )
                burst_seq = 0

                for tick in range(total_steady_sends):
                    target_ns = t_start_ns + tick * slot_ns
                    if time.perf_counter_ns() < target_ns:
                        gen_waiter.wait_until(target_ns)
                    d_id = tick & 7
                    s_sock, _r, lp = directions[d_id]
                    seq = sent_steady[d_id]
                    now_ns = time.perf_counter_ns()
                    pkt = struct.pack(_HDR_FMT, _MAGIC, d_id, _FLAG_STEADY, seq, now_ns) + pad_bytes
                    s_sock.sendto(pkt, ("127.0.0.1", lp))
                    sent_steady[d_id] = seq + 1

                    # Periodic single-route burst on route 0
                    if now_ns >= next_burst_ns:
                        bs_sock, _br, b_lp = directions[0]
                        for _ in range(burst_count):
                            b_ns = time.perf_counter_ns()
                            bpkt = (
                                struct.pack(_HDR_FMT, _MAGIC, 0, _FLAG_BURST, burst_seq, b_ns)
                                + pad_bytes
                            )
                            bs_sock.sendto(bpkt, ("127.0.0.1", b_lp))
                            burst_seq += 1
                            sent_burst[0] += 1
                        next_burst_ns += int(burst_interval_s * 1e9)
            finally:
                gen_waiter.close()

            # Drain tail packets (base_ms + 5*sigma_ms + 300ms margin)
            drain_s = max(0.35, (base_ms + 5.0 * sigma_ms) / 1000.0 + 0.3)
            time.sleep(drain_s)

            stop_mon.set()
            t_mon.join(timeout=2.0)
            stop_rx.set()
            for t in rx_threads:
                t.join(timeout=2.0)

            # Stop engine cleanly so it writes timing_out JSON
            eng_proc.stdin.write("STOP\n")
            eng_proc.stdin.flush()
            eng_proc.stdin.close()
            eng_proc.wait(timeout=15.0)
            t_out.join(timeout=2.0)

            engine_timing = json.loads(timing_out.read_text(encoding="utf-8"))

            # Aggregate receiver metrics
            all_e2e = array("q")
            per_dir_receiver = []
            for d_id in range(8):
                all_e2e.extend(recv_lat_ns[d_id])
                per_dir_receiver.append(
                    {
                        "dir": d_id,
                        "sent_steady": sent_steady[d_id],
                        "recv_steady": recv_steady[d_id],
                        "missing_steady": sent_steady[d_id] - recv_steady[d_id],
                        "sent_burst": sent_burst[d_id],
                        "recv_burst": recv_burst[d_id],
                        "bad_src_port": bad_src_port[d_id],
                        "bad_payload": bad_payload[d_id],
                        "out_of_order": out_of_order[d_id],
                        "duplicates": dup_count[d_id],
                        "e2e_latency": _summarize_ns(recv_lat_ns[d_id]),
                        "burst_e2e_latency": _summarize_ns(burst_lat_ns[d_id]) if sent_burst[d_id] else None,
                    }
                )

            worst_p99_lateness = max(
                r["lateness"]["p99_ms"] for r in engine_timing["per_rule"]
            )
            worst_max_lateness = max(
                r["lateness"]["max_ms"] for r in engine_timing["per_rule"]
            )

            return {
                "label": label,
                "config": {
                    "duration_s": duration_s,
                    "base_ms": base_ms,
                    "sigma_ms": sigma_ms,
                    "loss_pct": loss_pct,
                    "pps_per_dir": pps_per_dir,
                    "total_pps": pps_per_dir * 8,
                    "payload_bytes": payload_bytes,
                    "spin_us": spin_us,
                    "force_timer_fallback": force_timer_fallback,
                    "burst_interval_s": burst_interval_s,
                    "burst_count": burst_count if burst_interval_s > 0 else 0,
                    "with_gui": with_gui,
                    "target_binary": "UdpLinkSim.exe" if exe_path else "python -m udplinksim",
                },
                "engine_timer_mode": engine_timing["timer_mode"],
                "stats_snapshots_received": stats_count,
                "engine_cpu_pct_mean": round(sum(eng_cpu_samples) / len(eng_cpu_samples), 2) if eng_cpu_samples else 0.0,
                "engine_cpu_pct_max": round(max(eng_cpu_samples), 2) if eng_cpu_samples else 0.0,
                "engine_rss_mb_max": round(max(eng_rss_mb_samples), 2) if eng_rss_mb_samples else 0.0,
                "gui_cpu_pct_mean": round(sum(gui_cpu_samples) / len(gui_cpu_samples), 2) if gui_cpu_samples else 0.0,
                "worst_route_lateness_p99_ms": round(worst_p99_lateness, 4),
                "worst_route_lateness_max_ms": round(worst_max_lateness, 4),
                "overall_lateness": engine_timing["overall_lateness"],
                "overall_receiver_e2e": _summarize_ns(all_e2e),
                "total_sent_steady": sum(sent_steady),
                "total_recv_steady": sum(recv_steady),
                "total_sent_burst": sum(sent_burst),
                "total_recv_burst": sum(recv_burst),
                "total_bad_src_port": sum(bad_src_port),
                "total_bad_payload": sum(bad_payload),
                "total_out_of_order": sum(out_of_order),
                "total_duplicates": sum(dup_count),
                "engine_per_rule": engine_timing["per_rule"],
                "receiver_per_dir": per_dir_receiver,
                "listeners": engine_timing["listeners"],
            }
        finally:
            if eng_proc.poll() is None:
                eng_proc.kill()
                eng_proc.wait(timeout=5)
            if gui_proc is not None and gui_proc.poll() is None:
                try:
                    gp = psutil.Process(gui_proc.pid)
                    for ch in gp.children(recursive=True):
                        ch.kill()
                    gp.kill()
                except psutil.Error:
                    pass
                gui_proc.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="UdpLinkSim benchmark & soak suite")
    parser.add_argument(
        "--mode",
        choices=["ab", "short", "soak"],
        required=True,
        help="ab=spin/timer A/B comparison, short=M0/M1 short+burst+GUI, soak=30min 8-dir soak",
    )
    parser.add_argument("--duration", type=float, default=None, help="Override duration in seconds")
    parser.add_argument("--spin-us", type=int, default=0, help="Spin microseconds for short/soak")
    parser.add_argument("--use-exe", action="store_true", help="Run against dist/UdpLinkSim.exe")
    parser.add_argument("--out", required=True, help="Output JSON report path")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    exe = (root / "dist" / "UdpLinkSim.exe") if args.use_exe else None
    if exe is not None and not exe.is_file():
        raise FileNotFoundError(f"Packaged exe not found: {exe}")

    vm_info = collect_sanitized_vm_info()
    results: list[dict[str, Any]] = []

    if args.mode == "ab":
        dur = args.duration or 15.0
        cases = [
            ("fallback_1ms_spin0", 0, True),
            ("highres_spin0", 0, False),
            ("highres_spin250us", 250, False),
            ("highres_spin500us", 500, False),
        ]
        for label, spin_us, fb in cases:
            print(f"==> Running A/B case: {label} ({dur}s)...", flush=True)
            res = run_single_benchmark(
                label=label,
                duration_s=dur,
                base_ms=20.0,
                sigma_ms=0.0,
                pps_per_dir=100.0,
                spin_us=spin_us,
                force_timer_fallback=fb,
                exe_path=exe,
            )
            results.append(res)
            print(
                f"    worst_p99={res['worst_route_lateness_p99_ms']:.3f}ms "
                f"worst_max={res['worst_route_lateness_max_ms']:.3f}ms "
                f"cpu={res['engine_cpu_pct_mean']:.1f}% "
                f"rx={res['total_recv_steady']}/{res['total_sent_steady']}",
                flush=True,
            )

    elif args.mode == "short":
        dur = args.duration or 30.0
        print(f"==> Running M0/M1 short benchmark ({dur}s, 4 ports / 8 dirs, 100pps each, 20ms)...", flush=True)
        results.append(
            run_single_benchmark(
                label="short_steady_8dir_20ms",
                duration_s=dur,
                base_ms=20.0,
                pps_per_dir=100.0,
                spin_us=args.spin_us,
                exe_path=exe,
            )
        )
        print("==> Running single-route burst + live GUI activity benchmark (20s)...", flush=True)
        results.append(
            run_single_benchmark(
                label="short_burst_and_gui_activity",
                duration_s=20.0,
                base_ms=20.0,
                pps_per_dir=100.0,
                spin_us=args.spin_us,
                burst_interval_s=5.0,
                burst_count=200,
                with_gui=True,
                exe_path=exe,
            )
        )

    elif args.mode == "soak":
        dur = args.duration or 1800.0  # 30 minutes
        print(
            f"==> Running M3 30-minute soak ({dur}s, 4 ports / 8 dirs, 100pps each, 20ms, periodic burst + live GUI)...",
            flush=True,
        )
        results.append(
            run_single_benchmark(
                label="soak_30min_8dir_20ms",
                duration_s=dur,
                base_ms=20.0,
                pps_per_dir=100.0,
                spin_us=args.spin_us,
                burst_interval_s=300.0,  # Single-route 200-pkt burst every 5 minutes
                burst_count=200,
                with_gui=True,
                exe_path=exe,
            )
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "vm_conditions": vm_info,
        "results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"==> Saved report JSON: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
