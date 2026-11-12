"""G4 timing probe (diagnostic, never scored). Boots a kernel under a pinned QEMU with COM1 on
a TCP socket, timestamps every serial line on the host, and measures how guest heartbeat time
relates to host time.

  python -I tools/g4/timing_probe.py --run-id G4-P001 --qemu-dir <dir> --accel tcg --cpu max
         --kernel build/abraham-kernel.elf --limine-efi <BOOTX64.EFI> --seconds 60
         [--load N]   N host CPU burner processes during the measurement (controlled contention)

Recorded per run: per-line host monotonic ns; every ABR|TICK line with its host time; the
kernel's PIT/LAPIC calibration line; Windows timer resolution (NtQueryTimerResolution) before,
during and after; host logical CPU count; QEMU process CPU time (GetProcessTimes); host load
burners used; QEMU command. Evidence: evidence/g4/<run-id>/, sealed.
"""

import argparse
import ctypes
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abr_boot_001 as h  # noqa: E402

TICK = re.compile(r"ABR\|TICK\|uptime_s=(?P<s>\d+)(?P<rest>.*)$")


def timer_resolution():
    """(minimum, maximum, current) Windows timer resolution in ms."""
    mn, mx, cur = wintypes.ULONG(), wintypes.ULONG(), wintypes.ULONG()
    ctypes.windll.ntdll.NtQueryTimerResolution(ctypes.byref(mn), ctypes.byref(mx), ctypes.byref(cur))
    return {"coarsest_ms": mn.value / 1e4, "finest_ms": mx.value / 1e4, "current_ms": cur.value / 1e4}


def process_cpu_seconds(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    c, e, k, u = (wintypes.FILETIME() for _ in range(4))
    ok = ctypes.windll.kernel32.GetProcessTimes(handle, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u))
    ctypes.windll.kernel32.CloseHandle(handle)
    if not ok:
        return None
    ft = lambda f: ((f.dwHighDateTime << 32) | f.dwLowDateTime) / 1e7
    return {"kernel_s": ft(k), "user_s": ft(u)}


class PowerThrottlingState(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]


def opt_out_of_power_throttling(pid, mask=0x5):
    """Per-process only (this QEMU process): opt out of EcoQoS execution-speed throttling and of
    timer-resolution throttling. No system setting is changed."""
    PROCESS_SET_INFORMATION = 0x0200
    ProcessPowerThrottling = 4
    EXECUTION_SPEED, IGNORE_TIMER_RESOLUTION = 0x1, 0x4
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if not handle:
        return {"ok": False, "error": ctypes.GetLastError()}
    state = PowerThrottlingState(1, mask & (EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION), 0)
    ok = ctypes.windll.kernel32.SetProcessInformation(handle, ProcessPowerThrottling, ctypes.byref(state),
                                                      ctypes.sizeof(state))
    err = ctypes.GetLastError()
    ctypes.windll.kernel32.CloseHandle(handle)
    return {"ok": bool(ok), "error": None if ok else err, "control_mask": state.ControlMask,
            "state_mask": state.StateMask}


def select_window(ticks, start_ns, end_ns):
    """0.31b (Echo F-029-03): the intended collection window. Ticks are (host_ns, uptime_s, rest);
    keep those whose host arrival time lies in [start_ns, end_ns], both ends included. The 0.29
    expression `... <= t / 1e9 - 0 or True` was never used and, because of `or True`, kept every tick."""
    return [t for t in ticks if start_ns <= t[0] <= end_ns]


def analyse(ticks):
    """Guest heartbeat seconds against host seconds over the given ticks (the first, partial second
    is skipped), as 0.29 reported it."""
    out = {"tick_lines": len(ticks)}
    if len(ticks) >= 3:
        first, last = ticks[1], ticks[-1]
        host_s = (last[0] - first[0]) / 1e9
        guest_s = last[1] - first[1]
        gaps = [(b[0] - a[0]) / 1e9 for a, b in zip(ticks[1:], ticks[2:])]
        out.update({
            "guest_seconds": guest_s, "host_seconds": round(host_s, 4),
            "guest_per_host_ratio": round(guest_s / host_s, 4) if host_s else None,
            "gap_mean_s": round(statistics.mean(gaps), 4), "gap_stdev_s": round(statistics.pstdev(gaps), 4),
            "gap_min_s": round(min(gaps), 4), "gap_max_s": round(max(gaps), 4),
            "consecutive": [s for _, s, _ in ticks] == list(range(ticks[0][1], ticks[0][1] + len(ticks))),
            "tick_rest_sample": [r for _, _, r in ticks[1:4]],
        })
    return out


def burn(stop_at):
    x = 0
    while time.monotonic() < stop_at:
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--qemu-dir", required=True)
    p.add_argument("--accel", choices=("tcg", "whpx"), required=True)
    p.add_argument("--cpu", required=True)
    p.add_argument("--kernel", required=True)
    p.add_argument("--limine-efi", required=True)
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--load", type=int, default=0)
    p.add_argument("--no-throttle", action="store_true",
                   help="opt this QEMU process out of Windows power/timer-resolution throttling")
    p.add_argument("--throttle-mask", type=lambda x: int(x, 0), default=0x5,
                   help="with --no-throttle: 0x1 execution speed (EcoQoS), 0x4 timer resolution, 0x5 both")
    args = p.parse_args()

    h.use_qemu(args.qemu_dir)
    run = h.EVIDENCE / "g4" / args.run_id
    if run.exists():
        raise SystemExit(f"REFUSED: {run} exists")
    esp = run / "esp"
    (esp / "EFI" / "BOOT").mkdir(parents=True)
    (esp / "boot" / "limine").mkdir(parents=True)
    kernel = Path(args.kernel).read_bytes()
    shutil.copyfile(args.limine_efi, esp / "EFI" / "BOOT" / "BOOTX64.EFI")
    (esp / "boot" / "abraham-kernel").write_bytes(kernel)
    conf = h.LIMINE_CONF.read_text(encoding="ascii").replace("{KERNEL_BLAKE2B}", hashlib.blake2b(kernel).hexdigest())
    (esp / "boot" / "limine" / "limine.conf").write_text(conf, encoding="ascii", newline="\n")
    shutil.copyfile(h.FW_VARS, run / "vars.fd")

    serial_port, qmp_port = h.free_port(), h.free_port()
    command = h.qemu_command(args.accel, args.cpu, run, esp, qmp_port, run / "unused-serial.log")
    i = command.index("-serial")
    command[i + 1] = f"tcp:127.0.0.1:{serial_port},server=on,wait=on"  # QEMU waits for us: no line lost

    meta = {"run_id": args.run_id, "label": "DIAGNOSTIC (G4 timing probe, not scored)",
            "accelerator": args.accel, "cpu_model": args.cpu, "qemu": h.first_line([str(h.QEMU), "--version"]),
            "qemu_executable_sha256": h.sha256(h.QEMU), "kernel_sha256": hashlib.sha256(kernel).hexdigest(),
            "limine_efi_sha256": h.sha256(args.limine_efi), "qemu_command": command,
            "host_logical_cpus": os.cpu_count(), "load_burners": args.load,
            "timer_resolution_before": timer_resolution(), "started_utc": h.utc()}
    lines = []
    out = open(run / "qemu-stderr.txt", "wb")
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=out)
    # QEMU is still waiting for the serial client here, so this applies before the guest runs.
    meta["power_throttling_opt_out"] = opt_out_of_power_throttling(proc.pid, args.throttle_mask) if args.no_throttle else None
    t0 = time.monotonic_ns()
    deadline = time.monotonic() + 30
    while True:
        try:
            sock = socket.create_connection(("127.0.0.1", serial_port), timeout=5)
            break
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)

    def reader():
        buf = b""
        while True:
            try:
                chunk = sock.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                lines.append((time.monotonic_ns() - t0, h.ANSI.sub("", raw.decode("latin-1")).strip("\r ")))

    threading.Thread(target=reader, daemon=True).start()
    qmp = h.Qmp(qmp_port, run / "qmp.jsonl", t0 / 1e9)
    ok = h.wait_for(lambda: any(l == h.OPERATIONAL for _, l in lines), 120)
    meta["operational"] = bool(ok)
    cpu_start, wall_start = process_cpu_seconds(proc.pid), time.monotonic()
    burners = []
    if ok and args.load:
        stop_at = time.monotonic() + args.seconds
        burners = [multiprocessing.Process(target=burn, args=(stop_at,)) for _ in range(args.load)]
        for b in burners:
            b.start()
    if ok:
        time.sleep(args.seconds / 2)
        meta["timer_resolution_during"] = timer_resolution()
        time.sleep(args.seconds / 2)
    for b in burners:
        b.join()
    cpu_end, wall_end = process_cpu_seconds(proc.pid), time.monotonic()
    meta["timer_resolution_after"] = timer_resolution()
    meta["registers"] = qmp.command("human-monitor-command", **{"command-line": "info registers"}).get("return")
    qmp.command("quit")
    meta["qemu_exit"] = proc.wait(timeout=20)
    out.close()
    sock.close()
    if cpu_start and cpu_end:
        used = (cpu_end["kernel_s"] + cpu_end["user_s"]) - (cpu_start["kernel_s"] + cpu_start["user_s"])
        meta["qemu_cpu_seconds_in_window"] = round(used, 3)
        meta["qemu_cpu_utilisation_in_window"] = round(used / (wall_end - wall_start), 3)

    with open(run / "serial-timed.jsonl", "w", encoding="ascii", errors="replace") as f:
        for t, l in lines:
            f.write(json.dumps({"t_ns": t, "line": l}) + "\n")
    ticks = [(t, int(m["s"]), m["rest"]) for t, l in lines for m in [TICK.search(l)] if m]
    # 0.31b (F-029-03): the measurement window is from the moment OPERATIONAL was seen (wall_start)
    # to the end of the measurement (wall_end), in the same host-ns scale as the line timestamps.
    start_ns, end_ns = round(wall_start * 1e9) - t0, round(wall_end * 1e9) - t0
    window = select_window(ticks, start_ns, end_ns)
    analysis = {"faults": [l for _, l in lines if l.startswith("ABR|FAULT")],
                "calibration": next((l for _, l in lines if "apic_ticks_per_10ms" in l), None),
                "banner": next((l for _, l in lines if l.startswith("ABR|BANNER")), None),
                **analyse(ticks)}  # top level: all ticks, exactly as 0.29 reported (comparable)
    analysis["window"] = {"start_ns": start_ns, "end_ns": end_ns, **analyse(window)}
    meta["analysis"] = analysis
    meta["ended_utc"] = h.utc()
    (run / "probe.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    h.seal(run)
    print(json.dumps({k: meta[k] for k in ("run_id", "accelerator", "cpu_model", "load_burners",
                                           "timer_resolution_during", "qemu_cpu_utilisation_in_window")
                      if k in meta} | {"analysis": analysis}, indent=1))


if __name__ == "__main__":
    main()
