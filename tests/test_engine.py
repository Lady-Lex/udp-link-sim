"""Functional and timing semantics tests for UdpEngine."""

from __future__ import annotations

import socket
import struct
import sys
import time
from contextlib import ExitStack

import pytest

from udplinksim.config import Rule
from udplinksim.engine import EngineOptions, UdpEngine


def _alloc_udp_ports(count: int) -> list[int]:
    """Allocate free ephemeral loopback UDP ports cleanly."""
    sockets = []
    ports = []
    try:
        for _ in range(count):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", 0))
            ports.append(s.getsockname()[1])
            sockets.append(s)
    finally:
        for s in sockets:
            s.close()
    return ports


def _bind_udp(port: int = 0) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", port))
    s.settimeout(2.0)
    return s


def test_four_shared_sockets_eight_directions_duplex_and_src_port():
    listen_ports = _alloc_udp_ports(4)
    with ExitStack() as stack:
        a_socks = [stack.enter_context(_bind_udp()) for _ in range(4)]
        b_socks = [stack.enter_context(_bind_udp()) for _ in range(4)]
        rules = []
        for i in range(4):
            lp = listen_ports[i]
            ap = a_socks[i].getsockname()[1]
            bp = b_socks[i].getsockname()[1]
            rules.append(Rule("127.0.0.1", lp, "127.0.0.1", ap, "127.0.0.1", bp, 5.0, 0.0, 0.0))
            rules.append(Rule("127.0.0.1", lp, "127.0.0.1", bp, "127.0.0.1", ap, 5.0, 0.0, 0.0))

        engine = UdpEngine(rules, EngineOptions(stats_interval_ms=0))
        engine.start()
        try:
            assert len(engine.snapshot()["listeners"]) == 4
            assert len(engine.snapshot()["rules"]) == 8

            for i in range(4):
                lp = listen_ports[i]
                for seq in range(5):
                    pa = f"A{i}-{seq}".encode()
                    pb = f"B{i}-{seq}".encode()
                    a_socks[i].sendto(pa, ("127.0.0.1", lp))
                    b_socks[i].sendto(pb, ("127.0.0.1", lp))

            for i in range(4):
                lp = listen_ports[i]
                got_b = []
                got_a = []
                for _ in range(5):
                    data, peer = b_socks[i].recvfrom(4096)
                    assert peer == ("127.0.0.1", lp)  # Same shared bound socket!
                    got_b.append(data)
                    data2, peer2 = a_socks[i].recvfrom(4096)
                    assert peer2 == ("127.0.0.1", lp)
                    got_a.append(data2)
                assert got_b == [f"A{i}-{s}".encode() for s in range(5)]
                assert got_a == [f"B{i}-{s}".encode() for s in range(5)]
        finally:
            engine.stop()


def test_exact_match_precedence_and_two_changing_sender_ports_fixed_target():
    listen_port = _alloc_udp_ports(1)[0]
    with ExitStack() as stack:
        exact_sender = stack.enter_context(_bind_udp())
        transient_1 = stack.enter_context(_bind_udp())
        transient_2 = stack.enter_context(_bind_udp())
        exact_target = stack.enter_context(_bind_udp())
        wild_target = stack.enter_context(_bind_udp())

        rules = [
            Rule(
                "127.0.0.1", listen_port,
                "127.0.0.1", exact_sender.getsockname()[1],
                "127.0.0.1", exact_target.getsockname()[1],
                1.0, 0.0, 0.0,
            ),
            Rule(
                "127.0.0.1", listen_port,
                "127.0.0.1", 0,  # Wildcard port on same IP
                "127.0.0.1", wild_target.getsockname()[1],
                1.0, 0.0, 0.0,
            ),
        ]
        engine = UdpEngine(rules, EngineOptions(stats_interval_ms=0))
        engine.start()
        try:
            exact_sender.sendto(b"EXACT", ("127.0.0.1", listen_port))
            transient_1.sendto(b"WILD1", ("127.0.0.1", listen_port))
            transient_2.sendto(b"WILD2", ("127.0.0.1", listen_port))

            d_ex, p_ex = exact_target.recvfrom(4096)
            assert d_ex == b"EXACT"
            assert p_ex == ("127.0.0.1", listen_port)

            got_wild = []
            for _ in range(2):
                d_w, p_w = wild_target.recvfrom(4096)
                assert p_w == ("127.0.0.1", listen_port)
                got_wild.append(d_w)
            assert set(got_wild) == {b"WILD1", b"WILD2"}
        finally:
            engine.stop()


def test_empty_and_binary_datagram_preservation():
    listen_port = _alloc_udp_ports(1)[0]
    with ExitStack() as stack:
        sender = stack.enter_context(_bind_udp())
        receiver = stack.enter_context(_bind_udp())
        rule = Rule(
            "127.0.0.1", listen_port,
            "127.0.0.1", sender.getsockname()[1],
            "127.0.0.1", receiver.getsockname()[1],
            1.0, 0.0, 0.0,
        )
        engine = UdpEngine([rule], EngineOptions(stats_interval_ms=0))
        engine.start()
        try:
            payloads = [
                b"",  # 0-byte empty datagram!
                bytes(range(256)),  # Full binary 0x00..0xFF
                b"\x00\xff\r\n\x1a" * 1024,  # 5 KiB binary
            ]
            for p in payloads:
                sender.sendto(p, ("127.0.0.1", listen_port))
                got, peer = receiver.recvfrom(65535)
                assert got == p
                assert peer == ("127.0.0.1", listen_port)
        finally:
            engine.stop()


def test_early_5ms_arrival_before_prior_100ms_deadline():
    """Critical M1/timing requirement: a 5ms packet arriving after a 100ms packet
    MUST wake the timer thread and be sent around +5ms, NOT blocked behind 100ms!
    """
    listen_port = _alloc_udp_ports(1)[0]
    with ExitStack() as stack:
        slow_sender = stack.enter_context(_bind_udp())
        fast_sender = stack.enter_context(_bind_udp())
        receiver = stack.enter_context(_bind_udp())

        rules = [
            Rule(
                "127.0.0.1", listen_port,
                "127.0.0.1", slow_sender.getsockname()[1],
                "127.0.0.1", receiver.getsockname()[1],
                100.0, 0.0, 0.0,
            ),
            Rule(
                "127.0.0.1", listen_port,
                "127.0.0.1", fast_sender.getsockname()[1],
                "127.0.0.1", receiver.getsockname()[1],
                5.0, 0.0, 0.0,
            ),
        ]
        engine = UdpEngine(rules, EngineOptions(stats_interval_ms=0))
        engine.start()
        try:
            t_slow_send = time.perf_counter()
            slow_sender.sendto(b"SLOW_100MS", ("127.0.0.1", listen_port))
            time.sleep(0.010)  # Let TX thread arm the 100ms waitable timer
            t_fast_send = time.perf_counter()
            fast_sender.sendto(b"FAST_5MS", ("127.0.0.1", listen_port))

            first_data, _ = receiver.recvfrom(1024)
            t_first_recv = time.perf_counter()
            second_data, _ = receiver.recvfrom(1024)
            t_second_recv = time.perf_counter()

            fast_elapsed_ms = (t_first_recv - t_fast_send) * 1000.0
            slow_elapsed_ms = (t_second_recv - t_slow_send) * 1000.0

            assert first_data == b"FAST_5MS"
            assert second_data == b"SLOW_100MS"
            assert fast_elapsed_ms < 35.0, f"FAST_5MS blocked behind 100ms! got {fast_elapsed_ms:.2f}ms"
            assert 90.0 <= slow_elapsed_ms <= 160.0
        finally:
            engine.stop()


def test_bernoulli_loss_zero_hundred_and_fifty_pct():
    listen_port = _alloc_udp_ports(1)[0]
    with ExitStack() as stack:
        s0 = stack.enter_context(_bind_udp())
        s100 = stack.enter_context(_bind_udp())
        s50 = stack.enter_context(_bind_udp())
        r0 = stack.enter_context(_bind_udp())
        r100 = stack.enter_context(_bind_udp())
        r50 = stack.enter_context(_bind_udp())
        r100.settimeout(0.2)
        r50.settimeout(0.3)

        rules = [
            Rule("127.0.0.1", listen_port, "127.0.0.1", s0.getsockname()[1], "127.0.0.1", r0.getsockname()[1], 0.0, 0.0, 0.0),
            Rule("127.0.0.1", listen_port, "127.0.0.1", s100.getsockname()[1], "127.0.0.1", r100.getsockname()[1], 0.0, 0.0, 100.0),
            Rule("127.0.0.1", listen_port, "127.0.0.1", s50.getsockname()[1], "127.0.0.1", r50.getsockname()[1], 0.0, 0.0, 50.0),
        ]
        engine = UdpEngine(rules, EngineOptions(stats_interval_ms=0, seed=42))
        engine.start()
        try:
            for i in range(20):
                s0.sendto(f"Z{i}".encode(), ("127.0.0.1", listen_port))
                s100.sendto(f"H{i}".encode(), ("127.0.0.1", listen_port))
            for i in range(200):
                s50.sendto(f"F{i}".encode(), ("127.0.0.1", listen_port))

            for i in range(20):
                assert r0.recvfrom(1024)[0] == f"Z{i}".encode()

            with pytest.raises(socket.timeout):
                r100.recvfrom(1024)

            got50 = 0
            while True:
                try:
                    r50.recvfrom(1024)
                    got50 += 1
                except socket.timeout:
                    break

            snap = engine.snapshot()
            assert snap["rules"][0]["rx"] == 20
            assert snap["rules"][0]["tx"] == 20
            assert snap["rules"][0]["loss_drops"] == 0

            assert snap["rules"][1]["rx"] == 20
            assert snap["rules"][1]["tx"] == 0
            assert snap["rules"][1]["loss_drops"] == 20

            assert snap["rules"][2]["rx"] == 200
            assert snap["rules"][2]["tx"] == got50
            assert snap["rules"][2]["tx"] + snap["rules"][2]["loss_drops"] == 200
            assert 70 <= got50 <= 130
        finally:
            engine.stop()


def test_gaussian_delay_reordering_allowed():
    listen_port = _alloc_udp_ports(1)[0]
    with ExitStack() as stack:
        sender = stack.enter_context(_bind_udp())
        receiver = stack.enter_context(_bind_udp())
        rule = Rule(
            "127.0.0.1", listen_port,
            "127.0.0.1", sender.getsockname()[1],
            "127.0.0.1", receiver.getsockname()[1],
            20.0, 12.0, 0.0,
        )
        engine = UdpEngine([rule], EngineOptions(stats_interval_ms=0, seed=123))
        engine.start()
        try:
            n = 40
            for seq in range(n):
                sender.sendto(struct.pack("!I", seq), ("127.0.0.1", listen_port))
                time.sleep(0.001)
            received = []
            for _ in range(n):
                data, _ = receiver.recvfrom(64)
                received.append(struct.unpack("!I", data)[0])
            assert sorted(received) == list(range(n))
            # With sigma=12ms and 1ms spacing, reordering MUST occur
            assert received != list(range(n))
        finally:
            engine.stop()


def test_bounded_queue_overflow_packets_and_bytes_drop_new():
    listen_port = _alloc_udp_ports(1)[0]
    with ExitStack() as stack:
        sender = stack.enter_context(_bind_udp())
        receiver = stack.enter_context(_bind_udp())
        receiver.settimeout(0.4)

        # Case 1: Packet limit = 3
        rule = Rule(
            "127.0.0.1", listen_port,
            "127.0.0.1", sender.getsockname()[1],
            "127.0.0.1", receiver.getsockname()[1],
            80.0, 0.0, 0.0,
        )
        engine = UdpEngine(
            [rule],
            EngineOptions(stats_interval_ms=0, max_rule_packets=3, max_rule_bytes=1024 * 1024),
        )
        engine.start()
        try:
            for i in range(6):
                sender.sendto(f"P{i}".encode(), ("127.0.0.1", listen_port))
            got = []
            while len(got) < 6:
                try:
                    got.append(receiver.recvfrom(1024)[0])
                except socket.timeout:
                    break
            # Drop-new: first 3 kept, last 3 dropped
            assert got == [b"P0", b"P1", b"P2"]
            st = engine.snapshot()["rules"][0]
            assert st["rx"] == 6
            assert st["tx"] == 3
            assert st["overflow_drops"] == 3
            assert st["loss_drops"] == 0
        finally:
            engine.stop()

        # Case 2: Byte limit = 250 bytes (each packet 100 bytes -> only 2 fit)
        engine2 = UdpEngine(
            [rule],
            EngineOptions(stats_interval_ms=0, max_rule_packets=100, max_rule_bytes=250),
        )
        engine2.start()
        try:
            for i in range(4):
                sender.sendto(bytes([i]) * 100, ("127.0.0.1", listen_port))
            got2 = []
            while len(got2) < 4:
                try:
                    got2.append(receiver.recvfrom(1024)[0][0])
                except socket.timeout:
                    break
            assert got2 == [0, 1]
            st2 = engine2.snapshot()["rules"][0]
            assert st2["overflow_drops"] == 2
        finally:
            engine2.stop()


def test_unmatched_peer_and_wsa10054_and_discarded_no_stale_sends():
    listen_port, dead_target_port = _alloc_udp_ports(2)
    with ExitStack() as stack:
        good_sender = stack.enter_context(_bind_udp())
        unmatched_sender = stack.enter_context(_bind_udp())
        good_receiver = stack.enter_context(_bind_udp())
        good_receiver.settimeout(0.5)

        # Rule 0 -> dead_target_port (triggers WSA10054 on Windows)
        # Rule 1 -> good_receiver with 400ms delay (for discard / no stale send check)
        rules = [
            Rule(
                "127.0.0.1", listen_port,
                "127.0.0.1", good_sender.getsockname()[1],
                "127.0.0.1", dead_target_port,
                0.0, 0.0, 0.0,
            ),
            Rule(
                "127.0.0.1", listen_port,
                "127.0.0.1", good_receiver.getsockname()[1],
                "127.0.0.1", good_sender.getsockname()[1],
                400.0, 0.0, 0.0,
            ),
        ]
        engine = UdpEngine(rules, EngineOptions(stats_interval_ms=0))
        engine.start()
        try:
            # 1) Unmatched peer check
            unmatched_sender.sendto(b"WHO", ("127.0.0.1", listen_port))
            # 2) Trigger WSA10054 by sending to closed dead_target_port then sending another packet
            for _ in range(5):
                good_sender.sendto(b"ICMP_TRIGGER", ("127.0.0.1", listen_port))
                time.sleep(0.015)

            # 3) Enqueue 4 packets with 400ms delay to verify discard on stop
            for i in range(4):
                good_receiver.sendto(f"STALE{i}".encode(), ("127.0.0.1", listen_port))
            time.sleep(0.05)

            snap = engine.snapshot()
            listener = snap["listeners"][0]
            assert listener["unmatched_packets"] == 1
            assert listener["last_unmatched_peer"] == f"127.0.0.1:{unmatched_sender.getsockname()[1]}"
            if sys.platform == "win32":
                assert listener["wsa10054"] >= 1

            stopped = engine.stop()
            assert stopped["discarded_pending"] == 4

            # Verify ZERO stale sends arrive after stop
            good_sender.settimeout(0.55)
            with pytest.raises(socket.timeout):
                good_sender.recvfrom(1024)
        finally:
            engine.stop()
