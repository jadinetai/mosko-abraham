"""ABRAHAM VM LAUNCHER 0.33: drive the launcher in a real console window, as a double-click does (D-ABR-024).

  python -I -B tools/console_probe.py --run-id <id> --runs-dir <dir> --kernel production|launchpad
         --action key-q|close-window [--hold S] [--out <probe.json>] [--exe <launcher>]
  python -I -B tools/console_probe.py --menu-key 1|2|3 --run-id <label> --runs-dir <dir> --action ... --out ...

With --menu-key the launcher is started with no kernel and no run id (only --runs-dir, so the test record does not go
into the operator's runs folder): it shows its menu exactly as on a double-click; the probe reads the menu from the
window, types the key, and follows the run folder the launcher creates. <label> then names the probe's files only.

Starts the launcher in its own classic console window (conhost.exe, a new window like the one Explorer opens on a
double-click), waits until the run's serial.log shows OPERATIONAL and then `--hold` more seconds, and then:
  1. reads back the characters the window is displaying (AttachConsole + ReadConsoleOutputCharacterW) and saves them
     as <run>.screen.txt next to --out: what the operator would see, as text;
  2. key-q:        types Q into the window's input (WriteConsoleInputW), as the operator pressing the key;
     close-window: closes the window (WM_CLOSE to the console window), as the operator clicking X;
  3. waits for the launcher to finish and checks that no QEMU of the pinned toolchain is left running.
For key-q it then reads the window again (the final result) and types a key to close it, because a launcher whose
window was made for it waits for a key at the end. Standard library and ctypes only. Writes only --out and the
screen files. The launcher is never given --plain or --no-wait: this is the operator's mode.
"""
import argparse
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

VML = Path(__file__).resolve().parents[1]
QEMU_EXE = Path.home() / "abraham-toolchain" / "qemu" / "11.1.0-weil-20260811" / "qemu-system-x86_64.exe"
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short), ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]


class CSBI(ctypes.Structure):
    _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD), ("wAttributes", wintypes.WORD),
                ("srWindow", SMALL_RECT), ("dwMaximumWindowSize", COORD)]


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD), ("wVirtualKeyCode", wintypes.WORD),
                ("wVirtualScanCode", wintypes.WORD), ("uChar", wintypes.WCHAR), ("dwControlKeyState", wintypes.DWORD)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", wintypes.WORD), ("_pad", wintypes.WORD), ("Event", KEY_EVENT_RECORD)]


GENERIC_RW = 0xC0000000
SHARE_RW = 0x3
OPEN_EXISTING = 3
k32.CreateFileW.restype = wintypes.HANDLE
k32.GetConsoleWindow.restype = wintypes.HWND


def processes():
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2:
            rows.append((parts[0], int(parts[1])))
    return rows


def pinned_qemu_running():
    # Image paths, so a QEMU from another folder is not counted.
    q = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | ForEach-Object { $_.Id.ToString() + ' ' + $_.Path }"],
                       capture_output=True, text=True).stdout.split("\n")
    return [l.strip() for l in q if l.strip() and str(QEMU_EXE).lower() in l.lower()]


def attach(pid):
    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        raise OSError(f"AttachConsole({pid}) failed: {ctypes.get_last_error()}")


def read_screen(pid):
    attach(pid)
    try:
        h = k32.CreateFileW("CONOUT$", GENERIC_RW, SHARE_RW, None, OPEN_EXISTING, 0, None)
        info = CSBI()
        k32.GetConsoleScreenBufferInfo(h, ctypes.byref(info))
        w = info.srWindow
        lines = []
        for y in range(w.Top, w.Bottom + 1):
            width = w.Right - w.Left + 1
            buf = ctypes.create_unicode_buffer(width)
            n = wintypes.DWORD()
            k32.ReadConsoleOutputCharacterW(h, buf, width, COORD(w.Left, y), ctypes.byref(n))
            lines.append(buf.value[:n.value].rstrip())
        k32.CloseHandle(h)
        return lines, {"columns": w.Right - w.Left + 1, "rows": w.Bottom - w.Top + 1}
    finally:
        k32.FreeConsole()


def type_key(pid, ch):
    attach(pid)
    try:
        h = k32.CreateFileW("CONIN$", GENERIC_RW, SHARE_RW, None, OPEN_EXISTING, 0, None)
        recs = (INPUT_RECORD * 2)()
        for i, down in enumerate((True, False)):
            recs[i].EventType = 1  # KEY_EVENT
            recs[i].Event.bKeyDown = down
            recs[i].Event.wRepeatCount = 1
            recs[i].Event.wVirtualKeyCode = ord(ch.upper())
            recs[i].Event.uChar = ch
        n = wintypes.DWORD()
        ok = k32.WriteConsoleInputW(h, recs, 2, ctypes.byref(n))
        k32.CloseHandle(h)
        return bool(ok) and n.value == 2
    finally:
        k32.FreeConsole()


def close_window(pid):
    attach(pid)
    hwnd = k32.GetConsoleWindow()
    k32.FreeConsole()  # detach first: the close event goes to every process still attached
    WM_CLOSE = 0x0010
    return bool(hwnd) and bool(u32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--runs-dir", required=True)
    ap.add_argument("--kernel", default="production")
    ap.add_argument("--action", choices=("key-q", "close-window"), required=True)
    ap.add_argument("--hold", type=float, default=20.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--exe", default=str(VML / "Abraham-VM-Launcher.exe"))
    ap.add_argument("--menu-key", choices=("1", "2", "3"))
    ap.add_argument("--freeze-at", type=float, help="0.33.1: freeze QEMU this many seconds after OPERATIONAL")
    ap.add_argument("--freeze-for", type=float, default=30.0)
    a = ap.parse_args()
    runs = Path(a.runs_dir).resolve()
    run = runs / a.run_id
    out = Path(a.out).resolve()
    rec = {"run_id": a.run_id, "action": a.action, "exe": a.exe, "steps": []}

    def step(what, **kw):
        rec["steps"].append({"t": round(time.monotonic() - t0, 2), "what": what, **kw})

    t0 = time.monotonic()
    before = {pid for name, pid in processes() if name.lower() == "abraham-vm-launcher.exe"}
    runs.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in runs.iterdir()}
    if a.menu_key:
        cmd = ["conhost.exe", a.exe, "--runs-dir", str(runs)]
    else:
        cmd = ["conhost.exe", a.exe, "--kernel", a.kernel, "--run-id", a.run_id, "--runs-dir", str(runs)]
    rec["command"] = cmd
    host = subprocess.Popen(cmd, creationflags=0x00000010)  # CREATE_NEW_CONSOLE: its own window
    step("conhost started", pid=host.pid)
    pid = None
    for _ in range(100):
        new = [p for name, p in processes() if name.lower() == "abraham-vm-launcher.exe" and p not in before]
        if new:
            pid = new[0]
            break
        time.sleep(0.1)
    step("launcher found", pid=pid)
    if a.menu_key:
        time.sleep(3.0)
        menu, _ = read_screen(pid)
        mshot = out.with_name(a.run_id + ".screen-menu.txt")
        mshot.write_text("\n".join(menu) + "\n", encoding="utf-8")
        rec["menu_shown"] = any("Choose the kernel to boot" in l for l in menu)
        rec["menu_key_typed"] = type_key(pid, a.menu_key)
        step("menu read and key typed", key=a.menu_key, file=mshot.name)
        for _ in range(100):
            new = [p for p in runs.iterdir() if p.name not in existing]
            if new:
                run = new[0]
                break
            time.sleep(0.1)
        rec["run_folder_created_by_the_launcher"] = run.name
    serial = run / "serial.log"
    op_at = None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if serial.is_file() and b"ABR|STATE|OPERATIONAL" in serial.read_bytes():
            op_at = time.monotonic()
            break
        time.sleep(0.25)
    step("serial.log shows OPERATIONAL" if op_at else "OPERATIONAL not seen within 120 s")
    if a.freeze_at is not None:
        time.sleep(a.freeze_at)
        qpid = json.loads((run / "live.json").read_text())["qemu_pid"]
        r = subprocess.run([sys.executable, "-I", "-B", str(VML / "tools" / "pause_qemu.py"), str(qpid), str(a.freeze_for)],
                           capture_output=True, text=True)
        rec["freeze"] = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {"error": r.stdout + r.stderr}
        step("QEMU frozen and resumed", seconds=a.freeze_for)
    time.sleep(a.hold)
    screen, size = read_screen(pid)
    shot = out.with_name(a.run_id + ".screen-running.txt")
    shot.write_text("\n".join(screen) + "\n", encoding="utf-8")
    step("window contents read", file=shot.name, **size)
    rec["running_qemu_before_action"] = pinned_qemu_running()
    if a.action == "key-q":
        rec["key_typed"] = type_key(pid, "q")
        step("Q typed into the window")
        end = time.monotonic() + 30
        while time.monotonic() < end and not (run / "RUN_SHA256SUMS.json").exists():
            time.sleep(0.25)
        time.sleep(1.0)
        screen2, _ = read_screen(pid)
        shot2 = out.with_name(a.run_id + ".screen-final.txt")
        shot2.write_text("\n".join(screen2) + "\n", encoding="utf-8")
        step("final window contents read", file=shot2.name)
        rec["waiting_for_a_key_at_the_end"] = any("Press any key to close this window." in l for l in screen2)
        type_key(pid, "x")
        step("a key typed to close the window")
    else:
        rec["close_posted"] = close_window(pid)
        step("WM_CLOSE posted to the console window")
    try:
        host.wait(timeout=30)
    except subprocess.TimeoutExpired:
        step("conhost still running after 30 s")
    step("conhost exited", code=host.returncode)
    time.sleep(1.0)
    rec["launcher_still_running"] = any(p == pid for _, p in processes())
    rec["pinned_qemu_left"] = pinned_qemu_running()
    rec["run_sealed"] = (run / "RUN_SHA256SUMS.json").exists()
    launch = json.loads((run / "launch.json").read_text()) if (run / "launch.json").exists() else {}
    rec["launch_result"] = launch.get("result")
    rec["shutdown"] = launch.get("shutdown")
    ok = (op_at is not None and rec["run_sealed"] and not rec["pinned_qemu_left"] and not rec["launcher_still_running"]
          and (launch.get("shutdown") or {}).get("mode") == "CLEAN_QMP_QUIT"
          and any("KERNEL BOOT       : OPERATIONAL" in l for l in screen))
    if a.action == "key-q":
        ok = ok and rec.get("key_typed") and rec.get("waiting_for_a_key_at_the_end")
    if a.menu_key:
        ok = ok and rec.get("menu_shown") and rec.get("menu_key_typed")
    if a.freeze_at is not None:
        # The boot row carries a short marker; the CLOCK row (0.33.1) states the DEGRADED clock and the kernel's report.
        rec["panel_shows_the_pause"] = (
            any(l.startswith(" KERNEL BOOT") and "OPERATIONAL" in l and "clock gap" in l for l in screen)
            and any(l.startswith(" CLOCK") and "DEGRADED" in l and "reported by the kernel" in l and "cause not established" in l
                    for l in screen))
        ok = ok and rec["panel_shows_the_pause"]
    rec["verdict"] = "PASS" if ok else "FAIL"
    out.write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps({k: rec[k] for k in ("run_id", "action", "verdict", "launch_result", "pinned_qemu_left", "run_sealed")}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
