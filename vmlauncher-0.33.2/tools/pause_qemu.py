"""ABRAHAM VM LAUNCHER 0.33.1 test tool: freeze a QEMU process for a while, as a host standby freezes it (F-VML-01).

  python -I -B tools/pause_qemu.py <qemu pid> <seconds>

Suspends every thread of the process (SuspendThread), waits, resumes them (ResumeThread), and prints a JSON line
with the threads touched and the host times. Refuses any process that is not the pinned QEMU. Nothing else is
changed; the launcher is not told. Standard library and ctypes only.
"""
import ctypes
import json
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

QEXE = Path.home() / "abraham-toolchain" / "qemu" / "11.1.0-weil-20260811" / "qemu-system-x86_64.exe"
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.OpenThread.restype = wintypes.HANDLE
k32.OpenProcess.restype = wintypes.HANDLE


class TE32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD), ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", wintypes.DWORD)]


def image(pid):
    h = k32.OpenProcess(0x1000, False, pid)
    buf = ctypes.create_unicode_buffer(1024)
    n = wintypes.DWORD(1024)
    ok = h and k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
    if h:
        k32.CloseHandle(h)
    return buf.value if ok else None


def threads(pid):
    snap = k32.CreateToolhelp32Snapshot(0x4, 0)
    e = TE32()
    e.dwSize = ctypes.sizeof(TE32)
    out = []
    ok = k32.Thread32First(snap, ctypes.byref(e))
    while ok:
        if e.th32OwnerProcessID == pid:
            out.append(e.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def utc():
    return datetime.now(timezone.utc).isoformat()


def main():
    pid, seconds = int(sys.argv[1]), float(sys.argv[2])
    img = image(pid)
    if not img or img.lower() != str(QEXE).lower():
        print(json.dumps({"refused": f"pid {pid} is not the pinned QEMU ({img})"}))
        return 2
    handles = []
    for tid in threads(pid):
        h = k32.OpenThread(0x2, False, tid)  # THREAD_SUSPEND_RESUME
        if h:
            handles.append(h)
    t_suspend = utc()
    suspended = sum(1 for h in handles if k32.SuspendThread(h) != 0xFFFFFFFF)
    time.sleep(seconds)
    resumed = sum(1 for h in handles if k32.ResumeThread(h) != 0xFFFFFFFF)
    t_resume = utc()
    for h in handles:
        k32.CloseHandle(h)
    print(json.dumps({"pid": pid, "threads": len(handles), "suspended": suspended, "resumed": resumed,
                      "seconds": seconds, "suspended_utc": t_suspend, "resumed_utc": t_resume}))
    return 0 if suspended == resumed == len(handles) and handles else 1


if __name__ == "__main__":
    sys.exit(main())
