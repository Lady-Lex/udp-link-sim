"""Tests for Windows high-resolution waitable timer and fallback."""

from __future__ import annotations

import sys
import threading
import time

import pytest

from udplinksim.win_timer import HighResDeadlineWaiter


def test_high_res_timer_mode_and_accuracy():
    waiter = HighResDeadlineWaiter(spin_us=0)
    try:
        if sys.platform == "win32":
            assert waiter.timer_mode == "win32_high_res_waitable"
        t0 = time.perf_counter_ns()
        target = t0 + 15_000_000  # 15 ms
        interrupted = waiter.wait_until(target)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
        assert interrupted is False
        assert 14.0 <= elapsed_ms <= 35.0
    finally:
        waiter.close()


def test_fallback_timer_mode():
    waiter = HighResDeadlineWaiter(spin_us=0, force_fallback=True)
    try:
        if sys.platform == "win32":
            assert waiter.timer_mode == "win32_legacy_waitable_1ms"
        t0 = time.perf_counter_ns()
        target = t0 + 10_000_000  # 10 ms
        interrupted = waiter.wait_until(target)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
        assert interrupted is False
        assert 9.0 <= elapsed_ms <= 35.0
    finally:
        waiter.close()


def test_wake_interrupts_long_wait_quickly():
    waiter = HighResDeadlineWaiter(spin_us=0)
    try:
        def _waker():
            time.sleep(0.015)
            waiter.wake()

        t = threading.Thread(target=_waker)
        t0 = time.perf_counter_ns()
        t.start()
        interrupted = waiter.wait_until(t0 + 2_000_000_000)  # 2 seconds
        elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
        t.join(timeout=2.0)
        assert interrupted is True
        assert elapsed_ms < 200.0
    finally:
        waiter.close()
