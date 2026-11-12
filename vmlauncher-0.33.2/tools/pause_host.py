"""ABRAHAM VM LAUNCHER 0.33.2 test tool (D-ABR-026 3A): freeze QEMU AND the launcher together, as a host suspension
(a Windows standby) stops both, then resume them.

  python -I -B tools/pause_host.py <launcher pid> <qemu pid> <seconds>

Suspends every thread of QEMU, then of the launcher; waits; resumes the launcher first, then QEMU, so the launcher is
running again when the kernel's report of the gap arrives. Refuses any process that is not the pinned QEMU or an
Abraham-VM-Launcher.exe. Prints one JSON line. Standard library and ctypes only.
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


def thread_handles(pid):
    snap = k32.CreateToolhelp32Snapshot(0x4, 0)
    e = TE32()
    e.dwSize = ctypes.sizeof(TE32)
    out = []
    ok = k32.Thread32First(snap, ctypes.byref(e))
    while ok:
        if e.th32OwnerProcessID == pid:
            h = k32.OpenThread(0x2, False, e.th32ThreadID)
            if h:
                out.append(h)
        ok = k32.Thread32Next(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def utc():
    return datetime.now(timezone.utc).isoformat()


def main():
    lpid, qpid, seconds = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
    li, qi = image(lpid), image(qpid)
    if not qi or qi.lower() != str(QEXE).lower() or not li or not li.lower().endswith("\\abraham-vm-launcher.exe"):
        print(json.dumps({"refused": f"launcher {lpid} ({li}) / qemu {qpid} ({qi})"}))
        return 2
    q, l = thread_handles(qpid), thread_handles(lpid)
    t0 = utc()
    sq = sum(1 for h in q if k32.SuspendThread(h) != 0xFFFFFFFF)
    sl = sum(1 for h in l if k32.SuspendThread(h) != 0xFFFFFFFF)
    time.sleep(seconds)
    rl = sum(1 for h in l if k32.ResumeThread(h) != 0xFFFFFFFF)
    time.sleep(0.2)
    rq = sum(1 for h in q if k32.ResumeThread(h) != 0xFFFFFFFF)
    t1 = utc()
    for h in q + l:
        k32.CloseHandle(h)
    print(json.dumps({"launcher_pid": lpid, "qemu_pid": qpid, "launcher_threads": len(l), "qemu_threads": len(q),
                      "suspended": [sl, sq], "resumed": [rl, rq], "seconds": seconds, "suspended_utc": t0, "resumed_utc": t1}))
    return 0 if q and l and sq == rq == len(q) and sl == rl == len(l) else 1


if __name__ == "__main__":
    sys.exit(main())
