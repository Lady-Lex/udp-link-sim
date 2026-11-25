"""Windows high-resolution waitable timer (with fallback) and Job Object lifecycle helpers."""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _winmm = ctypes.WinDLL("winmm", use_last_error=True)

    CREATE_WAITABLE_TIMER_MANUAL_RESET = 0x00000001
    CREATE_WAITABLE_TIMER_HIGH_RESOLUTION = 0x00000002
    TIMER_ALL_ACCESS = 0x001F0003
    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT = 0x00000102
    WAIT_FAILED = 0xFFFFFFFF
    INFINITE = 0xFFFFFFFF

    # Job Object constants
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32.CreateWaitableTimerExW.argtypes = [
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _kernel32.CreateWaitableTimerExW.restype = wintypes.HANDLE

    _kernel32.CreateWaitableTimerW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    _kernel32.CreateWaitableTimerW.restype = wintypes.HANDLE

    _kernel32.SetWaitableTimer.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_int64),
        wintypes.LONG,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
    ]
    _kernel32.SetWaitableTimer.restype = wintypes.BOOL

    _kernel32.CancelWaitableTimer.argtypes = [wintypes.HANDLE]
    _kernel32.CancelWaitableTimer.restype = wintypes.BOOL

    _kernel32.CreateEventW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    _kernel32.CreateEventW.restype = wintypes.HANDLE

    _kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    _kernel32.SetEvent.restype = wintypes.BOOL

    _kernel32.WaitForMultipleObjects.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    _kernel32.WaitForMultipleObjects.restype = wintypes.DWORD

    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD

    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE

    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL

    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE

    _winmm.timeBeginPeriod.argtypes = [wintypes.UINT]
    _winmm.timeBeginPeriod.restype = wintypes.UINT

    _winmm.timeEndPeriod.argtypes = [wintypes.UINT]
    _winmm.timeEndPeriod.restype = wintypes.UINT


class HighResDeadlineWaiter:
    """Wait until an absolute monotonic deadline_ns, interruptible via wake().

    Uses Windows CREATE_WAITABLE_TIMER_HIGH_RESOLUTION when available, falling back
    to a legacy waitable timer + timeBeginPeriod(1) on older Windows, or threading.Event
    on non-Windows platforms.
    """

    def __init__(self, *, spin_us: int = 0, force_fallback: bool = False):
        if spin_us < 0:
            raise ValueError("spin_us must be >= 0")
        self.spin_ns = int(spin_us) * 1_000
        self._closed = False
        self._used_time_period = False
        self._timer_handle: int | None = None
        self._wake_handle: int | None = None
        self._handles_array = None
        self._fallback_event: threading.Event | None = None
        self.timer_mode = "python_event_fallback"

        if IS_WINDOWS:
            wake_h = _kernel32.CreateEventW(None, False, False, None)
            if not wake_h:
                raise OSError(ctypes.get_last_error(), "CreateEventW failed")
            self._wake_handle = wake_h

            timer_h = None
            if not force_fallback:
                timer_h = _kernel32.CreateWaitableTimerExW(
                    None,
                    None,
                    CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
                    TIMER_ALL_ACCESS,
                )
            if timer_h:
                self._timer_handle = timer_h
                self.timer_mode = "win32_high_res_waitable"
            else:
                # Fallback to standard waitable timer + 1ms multimedia timer period
                timer_h = _kernel32.CreateWaitableTimerW(None, True, None)
                if not timer_h:
                    _kernel32.CloseHandle(self._wake_handle)
                    self._wake_handle = None
                    raise OSError(
                        ctypes.get_last_error(), "CreateWaitableTimerW fallback failed"
                    )
                self._timer_handle = timer_h
                if _winmm.timeBeginPeriod(1) == 0:
                    self._used_time_period = True
                self.timer_mode = "win32_legacy_waitable_1ms"

            arr_type = wintypes.HANDLE * 2
            self._handles_array = arr_type(self._wake_handle, self._timer_handle)
        else:
            self._fallback_event = threading.Event()
            self.timer_mode = "python_event_fallback"

    def wake(self) -> None:
        """Interrupt any current or upcoming wait immediately."""
        if self._closed:
            return
        if IS_WINDOWS and self._wake_handle:
            _kernel32.SetEvent(self._wake_handle)
        elif self._fallback_event is not None:
            self._fallback_event.set()

    def wait_indefinite(self) -> None:
        """Wait until wake() is called."""
        if self._closed:
            return
        if IS_WINDOWS and self._wake_handle:
            _kernel32.WaitForSingleObject(self._wake_handle, INFINITE)
        elif self._fallback_event is not None:
            self._fallback_event.wait()
            self._fallback_event.clear()

    def wait_until(self, deadline_ns: int, stop_check=None) -> bool:
        """Wait until time.perf_counter_ns() >= deadline_ns or wake() is called.

        Returns True if interrupted by wake() (earlier deadline or stop), False if deadline reached.
        """
        if self._closed:
            return True
        now_ns = time.perf_counter_ns()
        remaining_ns = deadline_ns - now_ns
        if remaining_ns <= 0:
            return False

        if IS_WINDOWS and self._timer_handle and self._wake_handle:
            sleep_ns = remaining_ns - self.spin_ns
            if sleep_ns > 0:
                # Relative due time in 100ns units (negative = relative)
                ticks_100ns = max(1, sleep_ns // 100)
                due = ctypes.c_int64(-ticks_100ns)
                ok = _kernel32.SetWaitableTimer(
                    self._timer_handle, ctypes.byref(due), 0, None, None, False
                )
                if not ok:
                    raise OSError(ctypes.get_last_error(), "SetWaitableTimer failed")
                res = _kernel32.WaitForMultipleObjects(
                    2, self._handles_array, False, INFINITE
                )
                if res == WAIT_OBJECT_0:
                    # Woken by wake event (earlier packet or stop)
                    _kernel32.CancelWaitableTimer(self._timer_handle)
                    return True
                if res == WAIT_FAILED:
                    raise OSError(ctypes.get_last_error(), "WaitForMultipleObjects failed")

            # Optional bounded spin phase for final sub-millisecond window
            if self.spin_ns > 0:
                while time.perf_counter_ns() < deadline_ns:
                    if stop_check is not None and stop_check():
                        return True
                    # Non-blocking check whether wake event was signaled during spin
                    if _kernel32.WaitForSingleObject(self._wake_handle, 0) == WAIT_OBJECT_0:
                        return True
            return False

        # Non-Windows fallback
        assert self._fallback_event is not None
        sleep_s = max(0.0, (remaining_ns - self.spin_ns) / 1e9)
        if sleep_s > 0.0:
            woken = self._fallback_event.wait(timeout=sleep_s)
            if woken:
                self._fallback_event.clear()
                return True
        if self.spin_ns > 0:
            while time.perf_counter_ns() < deadline_ns:
                if stop_check is not None and stop_check():
                    return True
                if self._fallback_event.is_set():
                    self._fallback_event.clear()
                    return True
        return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if IS_WINDOWS:
            if self._wake_handle:
                _kernel32.SetEvent(self._wake_handle)
            if self._timer_handle:
                _kernel32.CancelWaitableTimer(self._timer_handle)
                _kernel32.CloseHandle(self._timer_handle)
                self._timer_handle = None
            if self._wake_handle:
                _kernel32.CloseHandle(self._wake_handle)
                self._wake_handle = None
            if self._used_time_period:
                _winmm.timeEndPeriod(1)
                self._used_time_period = False
        elif self._fallback_event is not None:
            self._fallback_event.set()


class KillOnCloseJob:
    """Windows Job Object that terminates all assigned child processes when closed or parent dies."""

    def __init__(self) -> None:
        self._handle: int | None = None
        if not IS_WINDOWS:
            return
        h_job = _kernel32.CreateJobObjectW(None, None)
        if not h_job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            h_job,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            err = ctypes.get_last_error()
            _kernel32.CloseHandle(h_job)
            raise OSError(err, "SetInformationJobObject failed")
        self._handle = h_job

    def assign_pid(self, pid: int) -> bool:
        """Assign an existing process ID to this job object."""
        if not IS_WINDOWS or not self._handle:
            return False
        h_proc = _kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid)
        )
        if not h_proc:
            return False
        try:
            ok = _kernel32.AssignProcessToJobObject(self._handle, h_proc)
            return bool(ok)
        finally:
            _kernel32.CloseHandle(h_proc)

    def close(self) -> None:
        if IS_WINDOWS and self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def start_parent_exit_watcher(parent_pid: int, on_parent_exit) -> threading.Thread | None:
    """Watch parent_pid handle on Windows and call on_parent_exit() immediately if parent terminates."""
    if not IS_WINDOWS or parent_pid <= 0:
        return None
    SYNCHRONIZE = 0x00100000
    h_parent = _kernel32.OpenProcess(SYNCHRONIZE, False, int(parent_pid))
    if not h_parent:
        # Parent may already be gone
        if os.getppid() != parent_pid:
            on_parent_exit()
        return None

    def _watch() -> None:
        try:
            _kernel32.WaitForSingleObject(h_parent, INFINITE)
        finally:
            _kernel32.CloseHandle(h_parent)
        on_parent_exit()

    t = threading.Thread(target=_watch, name="parent-exit-watcher", daemon=True)
    t.start()
    return t
