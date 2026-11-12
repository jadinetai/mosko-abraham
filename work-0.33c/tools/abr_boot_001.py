"""ABR-BOOT-001 harness: boot the Abraham kernel under QEMU + UEFI and judge the run.

  python tools/abr_boot_001.py run --run-id ABR-BOOT-001-R001 --limine-efi <BOOTX64.EFI>
         [--accel whpx|tcg] [--cpu host|max|qemu64] [--stable-seconds 15]
  python tools/abr_boot_001.py plumbing --run-id HARNESS-0001
         firmware + empty boot disk only: proves the harness, QMP and serial capture work.
         Never evidence of an Abraham boot.
  python tools/abr_boot_001.py series RUN_ID RUN_ID ...
         condition 7 (reproducibility) across runs plus build/build-info.json (repro mode)

Acceptance conditions (docs/ABR-BOOT-001.md):
  C1 UEFI loaded the selected bootloader   C5 no fault, no guest reset, ticks continuous
  C2 execution entered the Abraham kernel  C6 clean restart via the harness (QMP system_reset)
  C3 stable operational state reached      C7 reproducible (series: >= 2 PASS runs, same inputs,
  C4 Abraham diagnostic banner                identical repro builds)
                                           C8 complete evidence, sealed and re-verified

Standard library only. Writes only under evidence/. Never edits inputs. A verdict here is a
measurement, not an acceptance; acceptance is Jadin's.

0.31a additions (work-0.31 only; the 0.29 harness is unchanged in work-0.29):
  --kernel and --expect-kernel-sha256 are required: a kernel whose SHA-256 differs is refused
      before anything runs (no default kernel, no silent substitution).
  --profile 0.29 | 0.31a is required. 0.31a adds C9 (frame ownership, see judge_memory).
  --expect-memtest: the kernel is the diag-mem-exhaust build; C9 also requires its PASS summary.
  C0_configuration (Echo F-029-05): when the timer-resolution opt-out is requested it must have
      succeeded for every QEMU process, or the run FAILs; a control run without the opt-out is
      labelled as such.

0.31b corrections (work-0.31b; Echo F-031a-E01..E03, D-ABR-014):
  C0 is strict for every profile: flag exactly true, a verified record per QEMU process, started
      paused, cont after the opt-out. Without the opt-out the verdict is CONTROL_NOT_QUALIFYING
      (exit 3), never PASS.
  C9 is strict: exactly one ordered MEMCHECK summary per stage before OPERATIONAL, no malformed,
      duplicate, unknown-stage or post-OPERATIONAL line, internal consistency, and every MEMPIN
      record validated against its stage summary and the kernel's page-table count.
  --profile 0.31b adds C10 (initialization lifecycle and event log) and C11 (clock anomalies).

0.32 (work-0.32; D-ABR-018/019):
  --profile 0.32 = C0-C11 unchanged, plus C12 (services), judged on every boot against the closed production table
      (dev.net0, svc.counter, svc.netmon) and the Appendix A list parsed from the ratified baseline: nothing of the
      service manager before the OPERATIONAL event printout; one registry line in dependency order; dev.net0 skipped
      as not installed; svc.counter STARTING then RUNNING only after ready=PASS with equal counts; svc.netmon withheld
      by dev.net0; one second event dump consistent with those lines; complete status rounds every 5 s with the exact
      grammar; reasons Appendix A or NONE only; compromise NONE_KNOWN everywhere; the counter's value equal to its
      steps + 1, strictly increasing, and never above the loop wakes it could have used.

0.32b (work-0.32b; D-ABR-020, audit finding 4): C12 is hardened, for profile 0.32 and the new profile 0.32b alike:
  - readiness counts must be possible: probe = kernel = observed units, at least 1 and at most the declared budget
    (svc.counter: 1), and every later value must equal steps + the probe's units;
  - duration claims are checked: the probe time must be a measured number within the 1,000 us step budget (profile
    0.32b: and agree with its probe_timing verdict); the service event times must be non-decreasing, not earlier than
    the OPERATIONAL event records and not later than the first status round; every status round must lie between the
    heartbeats printed around it;
  - state reports must not contradict each other: the start-phase lines follow the dependency order; the entries of
    one round agree on its evaluation time; every status line's state follows that entry's transitions; its
    status/reason/liveness are a possible output of the status mapping for that state; its clock field follows the
    ABR|CLOCK lines before it.
  --profile 0.32b = C0-C11 + this C12 with the 0.32b readiness line (`probe_timing=` required).
"""

import argparse
import hashlib
import json
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

OS = Path(__file__).resolve().parents[1]
EVIDENCE = OS / "evidence"
QEMU_DIR = Path(r"C:\Program Files\qemu")
QEMU = QEMU_DIR / "qemu-system-x86_64.exe"
FW_CODE = QEMU_DIR / "share" / "edk2-x86_64-code.fd"
FW_VARS = QEMU_DIR / "share" / "edk2-i386-vars.fd"
KERNEL_ELF = OS / "build" / "abraham-kernel.elf"
LIMINE_CONF = OS / "boot" / "limine.conf"

ANSI = re.compile(r"\x1b\[[0-9;=?]*[A-Za-z]")
ENTRY = "ABR|ENTRY|abr_entry reached (NASM)"
KMAIN = "ABR|STAGE|kmain entered (Rust no_std)"
OPERATIONAL = "ABR|STATE|OPERATIONAL"
HUMAN_BANNER = re.compile(r"^ABRAHAM \| MOSKO native kernel \S+ \| ABR-BOOT-001$")
BANNER = re.compile(
    r"^ABR\|BANNER\|name=ABRAHAM\|version=(?P<version>[^|]+)\|arch=x86_64\|kernel=rust-no_std"
    r"\|entry=nasm\|boot=uefi\+limine\|boot_epoch=(?P<epoch>[0-9a-f]{16}|UNAVAILABLE)\|.*"
    r"\|status=(?P<status>AVAILABLE|DEGRADED)")
LOADER = re.compile(r"^ABR\|BOOTINFO\|loader=(?P<loader>[^|]+)\|base_revision_supported=(?P<rev>true|false)$")
TICK = re.compile(r"^ABR\|TICK\|uptime_s=(?P<s>\d+)\|spurious=(?P<spurious>\d+)(?:\|[a-z_]+=\d+)*$")
BDS_START = re.compile(r'^BdsDxe: starting Boot[0-9A-F]{4} "(?P<name>[^"]+)" from (?P<path>\S+)')


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def first_line(command):
    try:
        return subprocess.run(command, capture_output=True, text=True).stdout.splitlines()[0].strip()
    except (OSError, IndexError):
        return "UNAVAILABLE"


def serial_lines(path):
    if not path.is_file():
        return []
    text = path.read_bytes().decode("latin-1")
    return [ANSI.sub("", line).strip() for line in text.replace("\r", "").split("\n")]


def split_boots(lines):
    """Firmware output before the first kernel entry belongs to boot 1; each ENTRY starts a boot."""
    boots, current = [], []
    for line in lines:
        if line == ENTRY and any(l == ENTRY for l in current):
            boots.append(current)
            current = []
        current.append(line)
    boots.append(current)
    return boots


def opt_out_timer_throttling(pid):
    """0.29 G4 fix (TR-0017, approved by Jadin 2026-11-02): opt this QEMU process out of Windows
    timer-resolution throttling (PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION). Per process
    only; no system setting is changed. QEMU is started paused (-S) and resumed after this."""
    import ctypes
    from ctypes import wintypes

    class State(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

    handle = ctypes.windll.kernel32.OpenProcess(0x0200, False, pid)  # PROCESS_SET_INFORMATION
    if not handle:
        return {"ok": False, "error": ctypes.GetLastError()}
    state = State(1, 0x4, 0)  # control IGNORE_TIMER_RESOLUTION, state off = do not throttle
    ok = ctypes.windll.kernel32.SetProcessInformation(handle, 4, ctypes.byref(state), ctypes.sizeof(state))
    err = ctypes.GetLastError()
    ctypes.windll.kernel32.CloseHandle(handle)
    return {"ok": bool(ok), "error": None if ok else err, "control_mask": 0x4, "state_mask": 0}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Qmp:
    """Line-oriented QMP client; every message is logged with a host monotonic timestamp."""

    def __init__(self, port, log_path, t0, timeout=30.0):
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        self.sock.settimeout(None)
        self.file = self.sock.makefile("rwb")
        self.log = open(log_path, "a", encoding="ascii")
        self.t0 = t0
        self.events = []
        self.replies = queue.Queue()
        self.closed = threading.Event()
        self._record("greeting", json.loads(self.file.readline()))
        threading.Thread(target=self._reader, daemon=True).start()
        self.command("qmp_capabilities")

    def _record(self, kind, message):
        self.log.write(json.dumps({"t": round(time.monotonic() - self.t0, 3), "kind": kind,
                                   "message": message}, sort_keys=True) + "\n")
        self.log.flush()

    def _reader(self):
        try:
            for raw in self.file:
                message = json.loads(raw)
                if "event" in message:
                    self.events.append(message)
                    self._record("event", message)
                else:
                    self._record("reply", message)
                    self.replies.put(message)
        except (OSError, ValueError):
            pass
        finally:
            self.closed.set()

    def command(self, name, timeout=15.0, **arguments):
        request = {"execute": name, **({"arguments": arguments} if arguments else {})}
        self._record("command", request)
        self.file.write((json.dumps(request) + "\n").encode("ascii"))
        self.file.flush()
        return self.replies.get(timeout=timeout)


def wait_for(predicate, timeout, poll=0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(poll)
    return predicate()


def qemu_command(accel, cpu, run_dir, esp, qmp_port, serial_log):
    return [
        str(QEMU), "-machine", "q35", "-accel", accel, "-cpu", cpu, "-smp", "1", "-m", "256",
        "-display", "none", "-nodefaults", "-nic", "none",
        "-serial", f"file:{serial_log}",
        "-qmp", f"tcp:127.0.0.1:{qmp_port},server=on,wait=off",
        "-drive", f"if=pflash,format=raw,readonly=on,file={FW_CODE}",
        "-drive", f"if=pflash,format=raw,file={run_dir / 'vars.fd'}",
        "-drive", f"file=fat:ro:{esp},format=raw,if=virtio,readonly=on",
    ]


def seal(run_dir):
    sums = {p.relative_to(run_dir).as_posix(): sha256(p)
            for p in sorted(run_dir.rglob("*")) if p.is_file() and p.name != "RUN_SHA256SUMS.json"}
    (run_dir / "RUN_SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n")
    recheck = all(sha256(run_dir / name) == digest for name, digest in sums.items())
    return sums, recheck


def use_qemu(qemu_dir):
    """0.29: QEMU is chosen per run by absolute folder; nothing relies on PATH or on whatever
    happens to be installed in Program Files."""
    global QEMU_DIR, QEMU, FW_CODE, FW_VARS
    QEMU_DIR = Path(qemu_dir).resolve()
    QEMU = QEMU_DIR / "qemu-system-x86_64.exe"
    FW_CODE = QEMU_DIR / "share" / "edk2-x86_64-code.fd"
    FW_VARS = QEMU_DIR / "share" / "edk2-i386-vars.fd"
    for needed in (QEMU, FW_CODE, FW_VARS):
        if not needed.is_file():
            raise SystemExit(f"BLOCKED: {needed} missing")


def check_kernel_digest(args):
    """0.31a: refuse a kernel that is not the one named on the command line, before any run."""
    path = Path(args.kernel).resolve()
    if not path.is_file():
        raise SystemExit(f"BLOCKED: kernel {path} missing")
    actual = sha256(path)
    if actual != args.expect_kernel_sha256.lower():
        print(f"REFUSED: kernel {path} has SHA-256 {actual}, expected {args.expect_kernel_sha256}; nothing was run")
        raise SystemExit(2)
    return path


def boot(args, plumbing):
    global KERNEL_ELF
    use_qemu(args.qemu_dir)
    if not plumbing:
        KERNEL_ELF = check_kernel_digest(args)
    root = EVIDENCE / ("harness-selftest" if plumbing else "ABR-BOOT-001")
    run_dir = root / args.run_id
    if run_dir.exists():
        raise SystemExit(f"REFUSED: {run_dir} exists; run ids are never reused")
    accel, cpu = args.accel, args.cpu or ("host" if args.accel == "whpx" else "max")

    inputs = {"firmware_code": FW_CODE, "firmware_vars_template": FW_VARS}
    if not plumbing:
        if not args.limine_efi or not Path(args.limine_efi).is_file():
            raise SystemExit("BLOCKED: --limine-efi BOOTX64.EFI is required and must exist")
        for needed in (KERNEL_ELF, LIMINE_CONF):
            if not needed.is_file():
                raise SystemExit(f"BLOCKED: {needed} missing (build first: python tools/build.py kernel)")
        inputs.update(kernel_elf=KERNEL_ELF, limine_efi=Path(args.limine_efi), limine_conf=LIMINE_CONF)

    run_dir.mkdir(parents=True)
    esp = run_dir / "esp"
    (esp / "EFI" / "BOOT").mkdir(parents=True)
    staged = {}
    if not plumbing:
        (esp / "boot" / "limine").mkdir(parents=True)
        shutil.copyfile(inputs["limine_efi"], esp / "EFI" / "BOOT" / "BOOTX64.EFI")
        kernel_bytes = KERNEL_ELF.read_bytes()
        blake = hashlib.blake2b(kernel_bytes).hexdigest()  # BLAKE2b-512, as Limine expects
        if args.negative_hash:
            # Negative control: the config names the real kernel's hash, the disk holds a
            # kernel with one byte changed. Limine must refuse to load it.
            tampered = bytearray(kernel_bytes)
            tampered[-1] ^= 0xFF
            kernel_bytes = bytes(tampered)
        # 0.29 G7 negative tests: deliberately defective boot disks (copies only; recorded).
        defect = getattr(args, "stage_defect", None)
        if defect == "tamper-matching-hash":
            # Known LIMIT: whoever can edit the config can re-pin a tampered kernel.
            tampered = bytearray(kernel_bytes)
            tampered[-1] ^= 0xFF
            kernel_bytes = bytes(tampered)
            blake = hashlib.blake2b(kernel_bytes).hexdigest()
        if defect != "kernel-missing":
            (esp / "boot" / "abraham-kernel").write_bytes(kernel_bytes)
        conf = LIMINE_CONF.read_text(encoding="ascii").replace("{KERNEL_BLAKE2B}", blake)
        if defect == "bad-kernel-path":
            conf = conf.replace("boot():/boot/abraham-kernel", "boot():/boot/no-such-kernel")
        if defect != "config-missing":
            (esp / "boot" / "limine" / "limine.conf").write_text(conf, encoding="ascii", newline="\n")
        staged = {"stage_defect": defect, "kernel_blake2b_in_config": blake,
                  "staged_kernel_sha256": hashlib.sha256(kernel_bytes).hexdigest(),
                  "staged_kernel_tampered": bool(args.negative_hash)}
    shutil.copyfile(FW_VARS, run_dir / "vars.fd")

    serial_log = run_dir / "serial.log"
    port = free_port()
    command = qemu_command(accel, cpu, run_dir, esp, port, serial_log)
    opt_out = not getattr(args, "no_timer_opt_out", False)
    if opt_out:
        command.append("-S")  # start paused; resumed with QMP cont after the opt-out
    host = {"run_id": args.run_id, "kind": "harness plumbing self-test" if plumbing else "ABR-BOOT-001",
            "evidence_label": "HARNESS_SELFTEST" if plumbing else "VM_MEASURED",
            "accelerator": accel, "cpu_model": cpu, "qemu": first_line([str(QEMU), "--version"]),
            "qemu_dir": str(QEMU_DIR), "qemu_executable_sha256": sha256(QEMU),
            "timer_throttling_opt_out_enabled": opt_out,
            "profile": getattr(args, "profile", None), "expect_memtest": bool(getattr(args, "expect_memtest", False)),
            "expected_kernel_sha256": getattr(args, "expect_kernel_sha256", None),
            "host_python": sys.version.split()[0], "started_utc": utc(), "qemu_command": command,
            "inputs": {k: {"path": str(v), "sha256": sha256(v)} for k, v in inputs.items()},
            "staged": staged, "negative_hash_control": bool(getattr(args, "negative_hash", False))}
    build_info = OS / "build" / "build-info.json"
    if not plumbing and build_info.is_file():
        host["build_info"] = json.loads(build_info.read_text())

    t0 = time.monotonic()
    timeline = []
    restart = getattr(args, "restart", "cold")
    host["restart_mode"] = restart
    serial_boot2 = run_dir / "serial-boot2.log"

    def mark(what):
        timeline.append({"t": round(time.monotonic() - t0, 3), "what": what})

    def finish(proc, files):
        try:
            code = proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = f"KILLED({proc.wait()})"
        for f in files:
            f.close()
        return code

    stdout, stderr = open(run_dir / "qemu-stdout.txt", "wb"), open(run_dir / "qemu-stderr.txt", "wb")
    process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
    if opt_out:
        host["timer_throttling_opt_out_boot1"] = opt_out_timer_throttling(process.pid)
    qmp = qmp2 = None
    try:
        qmp = Qmp(port, run_dir / "qmp.jsonl", t0)
        mark("qmp connected")
        if opt_out:
            qmp.command("cont")
            mark("cont sent (after timer opt-out)")
        if plumbing:
            seen = wait_for(lambda: any(l.startswith("BdsDxe:") for l in serial_lines(serial_log)), 60)
            mark(f"firmware boot-manager output seen={bool(seen)}")
            time.sleep(3)
            host["status_before_quit"] = qmp.command("query-status").get("return")
        elif args.negative_hash:
            entered = wait_for(lambda: ENTRY in serial_lines(serial_log), args.negative_wait)
            mark(f"negative control observation ended, kernel_entered={bool(entered)}")
            host["status_before_quit"] = qmp.command("query-status").get("return")
        else:
            ok = wait_for(lambda: len(split_boots(serial_lines(serial_log))) >= 1 and
                          OPERATIONAL in split_boots(serial_lines(serial_log))[0], args.boot_timeout)
            mark(f"boot 1 operational={bool(ok)}")
            if ok and getattr(args, "kill_qemu_after_operational", False):
                process.kill()  # G7 fail-closed test: premature QEMU exit
                mark("QEMU killed by the harness (fail-closed test)")
            if ok:
                time.sleep(args.stable_seconds)
                mark("stability window 1 ended")
                host["status_after_window_1"] = qmp.command("query-status").get("return")
                host["registers_boot1"] = qmp.command(
                    "human-monitor-command", **{"command-line": "info registers"}).get("return")
                if restart == "warm":
                    qmp.command("system_reset")
                    mark("system_reset sent")
                    ok2 = wait_for(lambda: len(split_boots(serial_lines(serial_log))) >= 2 and
                                   OPERATIONAL in split_boots(serial_lines(serial_log))[1], args.boot_timeout)
                    mark(f"boot 2 operational={bool(ok2)}")
                    if ok2:
                        time.sleep(5)
                    host["status_after_window_2"] = qmp.command("query-status").get("return")
                else:
                    # Cold restart through the harness: clean QMP quit, then the same boot
                    # disk and the same firmware variable store in a new QEMU process.
                    qmp.command("quit")
                    mark("quit sent (cold restart)")
                    host["qemu_exit"] = finish(process, (stdout, stderr))
                    mark(f"boot 1 QEMU exited {host['qemu_exit']}")
                    port2 = free_port()
                    command2 = qemu_command(accel, cpu, run_dir, esp, port2, serial_boot2)
                    if opt_out:
                        command2.append("-S")
                    host["qemu_command_boot2"] = command2
                    stdout2 = open(run_dir / "qemu-stdout-boot2.txt", "wb")
                    stderr2 = open(run_dir / "qemu-stderr-boot2.txt", "wb")
                    process2 = subprocess.Popen(command2, stdout=stdout2, stderr=stderr2)
                    if opt_out:
                        host["timer_throttling_opt_out_boot2"] = opt_out_timer_throttling(process2.pid)
                    try:
                        qmp2 = Qmp(port2, run_dir / "qmp-boot2.jsonl", t0)
                        mark("boot 2 qmp connected")
                        if opt_out:
                            qmp2.command("cont")
                            mark("boot 2 cont sent (after timer opt-out)")
                        ok2 = wait_for(lambda: OPERATIONAL in serial_lines(serial_boot2), args.boot_timeout)
                        mark(f"boot 2 operational={bool(ok2)}")
                        if ok2:
                            time.sleep(5)
                        host["status_after_window_2"] = qmp2.command("query-status").get("return")
                        qmp2.command("quit")
                        mark("boot 2 quit sent")
                    finally:
                        host["qemu_exit_boot2"] = finish(process2, (stdout2, stderr2))
        if restart == "warm" or plumbing or args.negative_hash or "qemu_exit" not in host:
            qmp.command("quit")
            mark("quit sent")
    except (OSError, queue.Empty, ValueError) as error:
        mark(f"harness error: {error!r}")
    finally:
        if "qemu_exit" not in host:
            host["qemu_exit"] = finish(process, (stdout, stderr))
    host["ended_utc"] = utc()
    host["timeline"] = timeline
    host["qmp_events"] = qmp.events if qmp else []
    host["qmp_events_boot2"] = qmp2.events if qmp2 else []

    if plumbing:
        results = judge_plumbing(serial_log, host)
    elif args.negative_hash:
        results = judge_negative(serial_log, host)
    else:
        results = judge(serial_log, host, args)
    (run_dir / "host.json").write_text(json.dumps(host, indent=1, sort_keys=True) + "\n")
    (run_dir / "results.json").write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    sums, recheck = seal(run_dir)
    if not plumbing and not args.negative_hash:
        expected = {"serial.log", "qmp.jsonl", "host.json", "results.json", "qemu-stderr.txt",
                    *(("serial-boot2.log", "qmp-boot2.jsonl") if host.get("restart_mode") == "cold" else ()),
                    "esp/boot/abraham-kernel", "esp/EFI/BOOT/BOOTX64.EFI", "esp/boot/limine/limine.conf"}
        results["conditions"]["C8_evidence"] = {
            "pass": recheck and expected <= set(sums),
            "sealed_files": len(sums), "rehash_ok": recheck,
            "missing": sorted(expected - set(sums))}
        results["verdict"] = verdict(results)
        (run_dir / "results.json.final").write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
        # 0.29 fix (TR-0014 finding): re-seal so the final verdict is covered by the run seal,
        # and confirm every earlier digest is unchanged by the re-seal.
        resealed, recheck2 = seal(run_dir)
        if not recheck2 or any(resealed.get(k) != v for k, v in sums.items()) or "results.json.final" not in resealed:
            raise SystemExit("SEAL ERROR: re-seal changed an earlier digest or missed results.json.final")
    print(json.dumps(results, indent=1, sort_keys=True))
    print(f"{args.run_id}: {results['verdict']} (a measurement, not an acceptance)")
    codes = {"PASS": 0, "HARNESS_PLUMBING_OK": 0, "NEGATIVE_CONTROL_HELD": 0, "CONTROL_NOT_QUALIFYING": 3}
    return codes.get(results["verdict"], 1)


CORE = ["C0_configuration", "C1_loader", "C2_kernel_entered", "C3_operational", "C4_banner", "C5_no_crash",
        "C6_restart", "C8_evidence"]
PROFILE_CONDITIONS = {"0.29": [], "0.31a": ["C9_memory_ownership"],
                      "0.31b": ["C9_memory_ownership", "C10_lifecycle_events", "C11_clock"],
                      "0.32": ["C9_memory_ownership", "C10_lifecycle_events", "C11_clock", "C12_services"],
                      "0.32b": ["C9_memory_ownership", "C10_lifecycle_events", "C11_clock", "C12_services"],
                      "0.33": ["C9_memory_ownership", "C10_lifecycle_events", "C11_clock", "C12_services", "C13_launcher"]}


def verdict(results):
    """0.31b (F-031a-E01): PASS only if every scored condition passed. A missing condition, or an
    unknown profile, counts as a failure (fail closed). A run made without the timer opt-out whose
    other conditions all pass is CONTROL_NOT_QUALIFYING: it is labelled, and it is never PASS."""
    profile = results.get("profile")
    if profile not in PROFILE_CONDITIONS:
        return "FAIL"
    conds = results["conditions"]
    others = [c for c in CORE + PROFILE_CONDITIONS[profile] if c != "C0_configuration"]
    if not all(conds.get(c, {}).get("pass") is True for c in others):
        return "FAIL"
    c0 = conds.get("C0_configuration", {})
    if c0.get("pass") is True:
        return "PASS"
    if c0.get("control_not_qualifying") is True:
        return "CONTROL_NOT_QUALIFYING"
    return "FAIL"


def judge_configuration(host, cold):
    """0.31b C0 (F-031a-E01, F-029-05). Timed results count only if the Windows timer-resolution
    opt-out was requested AND verified for every QEMU process of the run: flag exactly true, a
    successful record per process (ok, control_mask 4, state_mask 0, no error), the process started
    paused (-S), and QMP cont sent after the opt-out. A run without the opt-out is a labelled control."""
    opt = host.get("timer_throttling_opt_out_enabled")
    timeline = [e.get("what") for e in host.get("timeline", []) if isinstance(e, dict)]

    def record_ok(r):
        return (isinstance(r, dict) and r.get("ok") is True and r.get("control_mask") == 4
                and r.get("state_mask") == 0 and r.get("error") is None)

    if opt is False:
        return {"pass": False, "control_not_qualifying": True,
                "timer_mode": "CONTROL_NO_OPT_OUT (not qualifying for timed acceptance; never PASS)"}
    items = {
        "opt_out_flag_exactly_true": opt is True,
        "boot1_opt_out_record_ok": record_ok(host.get("timer_throttling_opt_out_boot1")),
        "boot1_started_paused": "-S" in (host.get("qemu_command") or []),
        "boot1_cont_after_opt_out": "cont sent (after timer opt-out)" in timeline,
    }
    if cold:
        items.update({
            "boot2_opt_out_record_ok": record_ok(host.get("timer_throttling_opt_out_boot2")),
            "boot2_started_paused": "-S" in (host.get("qemu_command_boot2") or []),
            "boot2_cont_after_opt_out": "boot 2 cont sent (after timer opt-out)" in timeline,
        })
    return {"pass": all(items.values()), "control_not_qualifying": False, "items": items,
            "timer_mode": "OPT_OUT_REQUESTED_AND_VERIFIED" if all(items.values()) else "OPT_OUT_NOT_VERIFIED"}


MEM_STATE = re.compile(r"^ABR\|MEM\|state=(?P<state>[A-Z_]+)\|.*\|anomalies=(?P<anomalies>\d+)\|")
MEMCHECK_SUMMARY = re.compile(
    r"^ABR\|MEMCHECK\|stage=(?P<stage>[a-z_]+)\|pt_tables=(?P<tables>\d+)\|pt_in_bootloader=(?P<boot>\d+)"
    r"\|pt_pinned=(?P<ptp>\d+)\|kernel_pages=(?P<kp>\d+)\|pool_frames=(?P<pool>\d+)\|free_frames=(?P<free>\d+)"
    r"\|pinned=(?P<pinned>\d+)\|violations=(?P<violations>\d+)\|result=(?P<result>PASS|FAIL)$")
MEMCHECK_VIOLATION = re.compile(r"^ABR\|MEMCHECK\|stage=[a-z_]+\|violation=[A-Z0-9_]+\|.*$")
MEMPIN = re.compile(r"^ABR\|MEMPIN\|stage=(?P<stage>[a-z_]+)\|frame=(?P<frame>0x[0-9a-f]+)\|owner=(?P<owner>[A-Z_]+)"
                    r"\|in_pool=(?P<in_pool>true|false)\|free=(?P<free>true|false)$")
TIMER_TAKEN = re.compile(r"^ABR\|STAGE\|timer=.*\|page_table_frames_taken=(?P<n>\d+)\|")
MEMTEST_SUMMARY = re.compile(r"^ABR\|MEMTEST\|summary\|.*\|result=(?P<result>PASS|FAIL)$")


def judge_memory(boot_lines, expect_memtest):
    """0.31b strict C9 for one boot (F-031a-E02, F-031a-E03).

    Summaries: exact grammar; exactly one per required stage (init, timer; plus after_exhaust,
    after_release for memtest builds), in that order, no other stage, all before OPERATIONAL; any
    other ABR|MEMCHECK| line is malformed; any MEMCHECK or MEMPIN line after OPERATIONAL fails;
    PASS <=> violations=0; pt_tables = pt_in_bootloader + pt_pinned; pinned = pt_pinned.
    Pins: exact grammar; the MEMPIN lines of stage S lie between the previous summary and S's
    summary and carry stage S; their count equals S's 'pinned'; frames distinct, page-aligned,
    non-zero; owner PAGE_TABLE, in_pool=false, free=false; 'init' has none; 'timer' count equals the
    kernel's page_table_frames_taken; later stages list exactly the 'timer' set.
    Also: one allocator state line, READY, 0 anomalies; not a report-only build; memtest summary
    exactly once when expected, never otherwise."""
    op = boot_lines.index(OPERATIONAL) if OPERATIONAL in boot_lines else len(boot_lines)
    summaries, pins, malformed, violations, late = [], [], [], [], []
    for i, l in enumerate(boot_lines):
        if l.startswith("ABR|MEMCHECK|"):
            m = MEMCHECK_SUMMARY.match(l)
            if m:
                summaries.append((i, m.groupdict()))
            elif MEMCHECK_VIOLATION.match(l):
                violations.append(l)
            else:
                malformed.append(l)
            if i > op:
                late.append(l)
        elif l.startswith("ABR|MEMPIN|"):
            m = MEMPIN.match(l)
            if m:
                pins.append((i, m.groupdict()))
            else:
                malformed.append(l)
            if i > op:
                late.append(l)
    stages = ["init", "timer"] + (["after_exhaust", "after_release"] if expect_memtest else [])
    order_ok = [s["stage"] for _, s in summaries] == stages
    consistent = all(s["result"] == "PASS" and s["violations"] == "0"
                     and int(s["tables"]) == int(s["boot"]) + int(s["ptp"]) and s["pinned"] == s["ptp"]
                     for _, s in summaries)
    blocks, pins_ok, sets = {}, order_ok, {}
    if order_ok:
        previous = -1
        for idx, s in summaries:
            block = [p for i, p in pins if previous < i < idx]
            blocks[s["stage"]] = block
            frames = [int(p["frame"], 16) for p in block]
            sets[s["stage"]] = set(frames)
            pins_ok &= (len(block) == int(s["pinned"]) and len(set(frames)) == len(frames)
                        and all(f and f % 4096 == 0 for f in frames)
                        and all(p["stage"] == s["stage"] and p["owner"] == "PAGE_TABLE" and p["in_pool"] == "false"
                                and p["free"] == "false" for p in block))
            previous = idx
        pins_ok &= sum(len(b) for b in blocks.values()) == len(pins)  # no pin outside a stage block
    states = [m.groupdict() for m in map(MEM_STATE.match, boot_lines) if m]
    taken = [int(m["n"]) for m in map(TIMER_TAKEN.match, boot_lines[:op]) if m]
    nonfatal = [l for l in boot_lines if l.startswith("ABR|DIAG|memcheck_nonfatal")]
    memtest = [(i, m["result"]) for i, l in enumerate(boot_lines) for m in [MEMTEST_SUMMARY.match(l)] if m]
    items = {
        "allocator_ready_once": len(states) == 1 and states[0]["state"] == "READY",
        "no_map_anomalies": len(states) == 1 and states[0]["anomalies"] == "0",
        "no_malformed_memcheck_or_mempin": not malformed,
        "no_violation_lines": not violations,
        "nothing_after_operational": not late and op < len(boot_lines),
        "summaries_exactly_once_in_order": order_ok,
        "summaries_consistent_and_pass": bool(summaries) and consistent,
        "pins_valid_per_stage": pins_ok,
        "init_has_no_pins": order_ok and len(blocks.get("init", [None])) == 0,
        "timer_pins_equal_tables_created": order_ok and len(taken) == 1 and len(blocks.get("timer", [])) == taken[0],
        "later_pins_equal_timer_set": order_ok and all(sets[s] == sets["timer"] for s in stages[2:]),
        "not_a_report_only_build": not nonfatal,
        "memtest_pass": ([r for _, r in memtest] == ["PASS"] and memtest[0][0] < op) if expect_memtest else not memtest,
    }
    return {"pass": all(items.values()), "items": items, "summaries": [s for _, s in summaries],
            "pins": {k: [p["frame"] for p in v] for k, v in blocks.items()}, "malformed": malformed[:8],
            "violations": violations[:8], "after_operational": late[:8], "page_table_frames_taken": taken}


INIT_CHAIN = ["EARLY", "LOADER_VERIFIED", "MEMORY_OWNED", "MEMORY_VERIFIED", "CPU_TABLES_LOADED", "TIMER_RUNNING",
              "OWNERSHIP_VERIFIED", "OPERATIONAL"]
INIT_LINE = re.compile(r"^ABR\|INIT\|seq=(?P<seq>\d+)\|from=(?P<frm>[A-Z_]+)\|to=(?P<to>[A-Z_]+)(?P<rest>\|.*)?$")
EVENTS_LINE = re.compile(r"^ABR\|EVENTS\|recorded=(?P<recorded>\d+)\|dropped=(?P<dropped>\d+)\|capacity=(?P<capacity>\d+)"
                         r"\|lost_reentrant=(?P<lost>\d+)$")
EVENT_LINE = re.compile(r"^ABR\|EVENT\|seq=(?P<seq>\d+)\|uptime_ms=(?P<uptime>\d+|NONE)\|kind=(?P<kind>[A-Z]+)"
                        r"\|code=(?P<code>[A-Z0-9_]+)\|arg=(?P<arg>0x[0-9a-f]+)$")
EVENT_KINDS = {"INIT", "MEMORY", "TIMING", "FAULT"}


def judge_lifecycle(boot_lines, expect_memtest=False):
    """0.31b C10 for one boot (ABR-031-EVT-01, D-ABR-015). Lifecycle: exactly the 7 transitions
    EARLY -> ... -> OPERATIONAL, seq 1..7, in order, the last one immediately before
    ABR|STATE|OPERATIONAL; no other ABR|INIT line (no FAILED, no refusal). Event log: exactly one
    summary after OPERATIONAL with dropped=0, lost_reentrant=0, capacity=32, recorded equal to the
    EVENT lines printed; EVENT lines seq 1..n with uptime NONE or non-decreasing, kinds within
    INIT/MEMORY/TIMING/FAULT, no FAULT event; INIT events in the same order as the INIT lines;
    MEMORY events for both ownership checks; one TIMING TIMER_STARTED."""
    op = boot_lines.index(OPERATIONAL) if OPERATIONAL in boot_lines else None
    inits = [(i, m.groupdict()) for i, l in enumerate(boot_lines) for m in [INIT_LINE.match(l)] if m]
    stray_init = [l for l in boot_lines if l.startswith("ABR|INIT|") and not INIT_LINE.match(l)]
    expected = [(str(n + 1), INIT_CHAIN[n], INIT_CHAIN[n + 1]) for n in range(len(INIT_CHAIN) - 1)]
    got = [(d["seq"], d["frm"], d["to"]) for _, d in inits]
    summary = [(i, m.groupdict()) for i, l in enumerate(boot_lines) for m in [EVENTS_LINE.match(l)] if m]
    stray_events = [l for l in boot_lines if (l.startswith("ABR|EVENTS|") and not EVENTS_LINE.match(l))
                    or (l.startswith("ABR|EVENT|") and not EVENT_LINE.match(l))]
    events = [m.groupdict() for m in map(EVENT_LINE.match, boot_lines) if m]
    uptimes = [int(e["uptime"]) for e in events if e["uptime"] != "NONE"]
    s = summary[0][1] if len(summary) == 1 else {}
    items = {
        "operational_reached": op is not None,
        "init_chain_exact": got == expected and not stray_init and all(not d.get("rest") for _, d in inits),
        "last_transition_right_before_operational": bool(inits) and op is not None and inits[-1][0] == op - 1,
        "events_summary_once_after_operational": len(summary) == 1 and op is not None and summary[0][0] > op,
        "events_nothing_dropped_or_lost": s.get("dropped") == "0" and s.get("lost") == "0" and s.get("capacity") == "32",
        "events_count_matches": bool(s) and int(s["recorded"]) == len(events) <= 32 and not stray_events,
        "events_seq_consecutive": [int(e["seq"]) for e in events] == list(range(1, len(events) + 1)),
        "events_uptime_non_decreasing": uptimes == sorted(uptimes),
        "events_kinds_known_no_fault": bool(events) and all(e["kind"] in EVENT_KINDS and e["kind"] != "FAULT" for e in events),
        "init_events_match_init_lines": [e["code"] for e in events if e["kind"] == "INIT"] == [t for _, _, t in got],
        "memory_events_every_check": sum(1 for e in events if e["kind"] == "MEMORY" and e["code"] == "MEMCHECK_PASS")
                                     == (4 if expect_memtest else 2),
        "allocator_ready_event": sum(1 for e in events if e["kind"] == "MEMORY" and e["code"] == "ALLOCATOR_READY") == 1,
        "timer_started_event": sum(1 for e in events if e["kind"] == "TIMING" and e["code"] == "TIMER_STARTED") == 1,
    }
    return {"pass": all(items.values()), "items": items, "init": got, "events": len(events)}


TICK_FIELDS = re.compile(r"\|([a-z_]+)=(\d+)")


def judge_clock(boot_lines):
    """0.31b C11 for one boot (F-029-04): every heartbeat reports clock_anomalies=0 and no ABR|CLOCK
    line exists (no backward step, no forward jump, no heartbeat gap, no DEGRADED state)."""
    ticks = [dict(TICK_FIELDS.findall(l[len("ABR|TICK"):])) for l in boot_lines if TICK.match(l)]
    clock = [l for l in boot_lines if l.startswith("ABR|CLOCK|")]
    items = {"heartbeats_present": bool(ticks),
             "every_heartbeat_reports_zero_anomalies": bool(ticks) and all(t.get("clock_anomalies") == "0" for t in ticks),
             "no_clock_lines": not clock}
    return {"pass": all(items.values()), "items": items, "clock_lines": clock[:8], "heartbeats": len(ticks)}


# ---------------------------------------------------------------- 0.32 C12 (services; D-ABR-019, design §7)
HOME = OS.parent
BASELINE = HOME / "ABRAHAM_0.2_BASELINE.md"
REGISTRY_DOC = OS / "docs" / "KERNEL_DIAGNOSTICS.md"
SVC_TABLE = ["dev.net0", "svc.counter", "svc.netmon"]  # the closed production table, in table order
SVC_ORDER = ["dev.net0", "svc.counter", "svc.netmon"]  # its dependency order (ties by id)
SVC_REGISTRY = re.compile(r"^ABR\|SVC\|registry=OK\|entries=(?P<n>\d+)\|order=(?P<order>[a-z0-9.,]+)$")
SVC_SKIPPED = re.compile(r"^ABR\|SVC\|id=(?P<id>[a-z0-9.]+)\|start=SKIPPED\|installed=false\|kind=(?P<kind>SERVICE|ADAPTER)$")
SVC_WITHHELD = re.compile(r"^ABR\|SVC\|id=(?P<id>[a-z0-9.]+)\|start=WITHHELD\|dependency=(?P<dep>[a-z0-9.]+)"
                          r"\|dependency_state=(?P<st>[A-Z]+)$")
SVC_TRANSITION = re.compile(r"^ABR\|SVC\|id=(?P<id>[a-z0-9.]+)\|seq=(?P<seq>\d+)\|from=(?P<frm>[A-Z]+)\|to=(?P<to>[A-Z]+)"
                            r"(?:\|diag=(?P<diag>[A-Z0-9_]+))?$")
SVC_READY = re.compile(r"^ABR\|SVC\|id=(?P<id>[a-z0-9.]+)\|ready=PASS\|probe_units=(?P<pu>\d+)\|kernel_units=(?P<ku>\d+)"
                       r"\|observed=(?P<obs>\d+|NONE)\|probe_us=(?P<us>\d+|NONE)"
                       r"(?:\|probe_timing=(?P<timing>IN_BUDGET|OVERRUN|UNMEASURED))?$")
SVC_BUDGET = {"dev.net0": 0, "svc.counter": 1, "svc.netmon": 1}  # declared work budgets of the production table
SVC_INSTALLED = {"dev.net0": False, "svc.counter": True, "svc.netmon": True}
STEP_BUDGET_US = 1000
TOLERANCE_MS = 50  # a status time may precede the heartbeat line printed just before it by this much


def status_possible(installed, d):
    """The status mapping (design §5), re-stated: is (state, status, reason, liveness) a possible output for this
    entry with this clock field? Used to refuse self-contradictory status lines."""
    s = (d["state"], d["status"], d["reason"], d["liveness"])
    if not installed:
        return s[1:] == ("UNAVAILABLE", "NOT_INSTALLED", "UNKNOWN")
    if d["state"] == "FAILED":
        return s[1:] == ("UNAVAILABLE", "NONE", "LOST")
    if d["state"] == "DECLARED":
        return s[1:] in (("UNAVAILABLE", "NONE", "UNKNOWN"), ("UNAVAILABLE", "NOT_INSTALLED", "UNKNOWN"))
    if d["state"] in ("STARTING", "STOPPING", "STOPPED"):
        return s[1:] == ("UNAVAILABLE", "NONE", "UNKNOWN")
    if d["state"] == "RUNNING":
        if d["clock"] != "OK":
            return s[1:] == ("UNKNOWN", "OBSERVATION_STALE", "UNKNOWN")
        return s[1:] in (("UNKNOWN", "OBSERVATION_STALE", "STALE"), ("DEGRADED", "NONE", "LIVE"), ("AVAILABLE", "NONE", "LIVE"))
    return False


def status_contradictions(boot_lines, installed):
    """0.32b (finding 4): for every ABR|SVCSTATUS line, the state must follow the entry's transitions printed before
    it (DECLARED if none), the fields must be a possible mapping output, and the clock field must follow the ABR|CLOCK
    lines before it. Returns the offending lines (empty when consistent)."""
    state, degraded, bad = {}, False, []
    for l in boot_lines:
        if l.startswith("ABR|CLOCK|state=DEGRADED"):
            degraded = True
        m = SVC_TRANSITION.match(l)
        if m:
            state[m["id"]] = m["to"]
            continue
        s = SVC_STATUS.match(l)
        if s:
            d = s.groupdict()
            want_clock = "DEGRADED" if degraded else "OK"
            if (d["state"] != state.get(d["id"], "DECLARED") or not status_possible(installed.get(d["id"], True), d)
                    or d["clock"] not in (want_clock, "UNREADABLE")):
                bad.append(l)
    return bad
SVC_EVENTS = re.compile(r"^ABR\|SVCEVENTS\|from_seq=(?P<from_seq>\d+)\|recorded=(?P<recorded>\d+)\|dropped=(?P<dropped>\d+)"
                        r"\|capacity=(?P<capacity>\d+)\|lost_reentrant=(?P<lost>\d+)$")
SVC_EVENT = re.compile(r"^ABR\|SVCEVENT\|seq=(?P<seq>\d+)\|uptime_ms=(?P<uptime>\d+|NONE)\|kind=(?P<kind>[A-Z]+)"
                       r"\|code=(?P<code>[A-Z0-9_]+)\|arg=(?P<arg>0x[0-9a-f]+)$")
SVC_STATUS = re.compile(r"^ABR\|SVCSTATUS\|id=(?P<id>[a-z0-9.]+)\|state=(?P<state>[A-Z]+)\|status=(?P<status>[A-Z_]+)"
                        r"\|reason=(?P<reason>[A-Z_]+)\|liveness=(?P<liveness>[A-Z_]+)\|compromise=(?P<compromise>[A-Z_]+)"
                        r"\|observed_at_ms=(?P<at>\d+|NONE)\|clock=(?P<clock>[A-Z]+)\|value=(?P<value>\d+|NONE)"
                        r"\|steps=(?P<steps>\d+)\|overruns=(?P<overruns>\d+)$")
SVC_GRAMMARS = (SVC_REGISTRY, SVC_SKIPPED, SVC_WITHHELD, SVC_TRANSITION, SVC_READY, SVC_EVENTS, SVC_EVENT, SVC_STATUS)
# (code, arg) of the SERVICE records a clean production start must append, in order.
SVC_EXPECTED_EVENTS = [("SVC_REGISTRY_OK", 0x3), ("SVC_NOT_INSTALLED", 0x1), ("SVC_STARTING", 0x201), ("SVC_RUNNING", 0x202),
                       ("SVC_START_WITHHELD", 0x301)]


def appendix_a_codes():
    """The 27 Appendix A reason codes, parsed from the ratified baseline (never hard-coded here)."""
    try:
        text = BASELINE.read_text(encoding="utf-8")
        a = text[text.index("## Appendix A"):text.index("## Appendix B")]
    except (OSError, ValueError):
        return []
    return re.findall(r"^\| `([A-Z_]+)` \|", a, re.M)


def registered_codes():
    try:
        return {m.group(1) for l in REGISTRY_DOC.read_text(encoding="utf-8").splitlines()
                for m in [re.match(r"^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|", l)] if m}
    except OSError:
        return set()


def judge_services(boot_lines, profile="0.32"):
    """0.32 C12 for one boot (design §7), hardened in 0.32b (finding 4). Clean production expectations; every item
    must hold. `profile` 0.32b requires the 0.32b readiness line (probe_timing).

    End of capture: the harness ends a boot by quitting QEMU (cold) or resetting it (warm), which can cut the status
    round that is being printed at that moment. Exactly this is tolerated, and reported: a final ABR|SVCSTATUS line
    that is cut off (it is the boot's last ABR| line and does not match the grammar), and an incomplete final round
    after which the kernel printed nothing else. Anywhere else, a malformed line or an incomplete round FAILS."""
    public = appendix_a_codes()
    registered = registered_codes()
    op = boot_lines.index(OPERATIONAL) if OPERATIONAL in boot_lines else None
    ev_idx = next((i for i, l in enumerate(boot_lines) if EVENTS_LINE.match(l)), None)
    ev_recorded = int(EVENTS_LINE.match(boot_lines[ev_idx])["recorded"]) if ev_idx is not None else None
    svc = [(i, l) for i, l in enumerate(boot_lines) if l.startswith("ABR|SVC")]
    last_abr = max((i for i, l in enumerate(boot_lines) if l.startswith("ABR|")), default=-1)
    cut_line = None
    if svc and svc[-1][0] == last_abr and svc[-1][1].startswith("ABR|SVCSTATUS|") and not SVC_STATUS.match(svc[-1][1]):
        cut_line = svc.pop()[1]
    stray = [l for _, l in svc if not any(g.match(l) for g in SVC_GRAMMARS)]
    reg = [(i, m.groupdict()) for i, l in svc for m in [SVC_REGISTRY.match(l)] if m]
    skipped = [(i, m.groupdict()) for i, l in svc for m in [SVC_SKIPPED.match(l)] if m]
    withheld = [(i, m.groupdict()) for i, l in svc for m in [SVC_WITHHELD.match(l)] if m]
    trans = [(i, m.groupdict()) for i, l in svc for m in [SVC_TRANSITION.match(l)] if m]
    ready = [(i, m.groupdict()) for i, l in svc for m in [SVC_READY.match(l)] if m]
    dumps = [(i, m.groupdict()) for i, l in svc for m in [SVC_EVENTS.match(l)] if m]
    events = [m.groupdict() for _, l in svc for m in [SVC_EVENT.match(l)] if m]
    status = [(i, m.groupdict()) for i, l in svc for m in [SVC_STATUS.match(l)] if m]
    ticks = [(i, dict(TICK_FIELDS.findall(l[len("ABR|TICK"):]))) for i, l in enumerate(boot_lines) if TICK.match(l)]

    def of(rows, name):
        return [d for _, d in rows if d["id"] == name]

    counter_t = [(d["seq"], d["frm"], d["to"], d.get("diag")) for d in of(trans, "svc.counter")]
    counter_ready = [(i, d) for i, d in ready if d["id"] == "svc.counter"]
    t_idx = [i for i, d in trans if d["id"] == "svc.counter"]
    start_lines = [i for i, _ in reg + skipped + withheld + trans + ready]
    # status rounds: consecutive groups of one line per table entry, in table order
    rounds, ok_rounds, partial = [], True, []
    end_of_output = cut_line is not None
    for k in range(0, len(status), len(SVC_TABLE)):
        group = status[k:k + len(SVC_TABLE)]
        ids, idx = [d["id"] for _, d in group], [i for i, _ in group]
        contiguous = idx == list(range(idx[0], idx[0] + len(idx)))
        if ids == SVC_TABLE and contiguous:
            rounds.append({d["id"]: (i, d) for i, d in group})
            continue
        final = k + len(SVC_TABLE) >= len(status)
        nothing_after = idx[-1] == last_abr or (end_of_output and idx[-1] == max(i for i, _ in svc))
        if final and contiguous and ids == SVC_TABLE[:len(ids)] and nothing_after:
            partial = group  # cut by the end of capture
        else:
            ok_rounds = False
        break
    status = [x for x in status if x not in partial]
    times = [int(r["dev.net0"][1]["at"]) if r["dev.net0"][1]["at"].isdigit() else -1 for r in rounds]
    gaps = [b - a for a, b in zip(times, times[1:])]
    last_tick_s = int(ticks[-1][1]["uptime_s"]) if ticks else 0
    want_rounds = 1 + max(0, (last_tick_s * 1000 - (times[0] if times else 0) - 600) // 5100)
    seen_rounds = len(rounds) + (1 if (partial or cut_line) else 0)

    def static_ok(d):
        return (d["state"], d["status"], d["reason"], d["liveness"], d["compromise"], d["clock"], d["value"], d["steps"],
                d["overruns"]) == ("DECLARED", "UNAVAILABLE", "NOT_INSTALLED", "UNKNOWN", "NONE_KNOWN", "OK", "NONE", "0", "0")

    def counter_ok(r, at):
        d = r["svc.counter"][1]
        return ((d["state"], d["status"], d["reason"], d["liveness"], d["compromise"], d["clock"], d["overruns"])
                == ("RUNNING", "AVAILABLE", "NONE", "LIVE", "NONE_KNOWN", "OK", "0")
                and d["at"].isdigit() and 0 <= at - int(d["at"]) < 1000)

    def wake_bound_ok(r):
        i, d = r["svc.counter"]
        before = [t for j, t in ticks if j < i]
        if not before or not d["value"].isdigit():
            return d["value"].isdigit()
        t = before[-1]
        at = int(r["dev.net0"][1]["at"]) if r["dev.net0"][1]["at"].isdigit() else 0
        extra = max(0, at - int(t.get("uptime_s", "0")) * 1000) // 10 + 2
        return int(d["value"]) <= int(t.get("timer_irqs", "0")) + int(t.get("spurious", "0")) + 1 + extra

    values = [int(r["svc.counter"][1]["value"]) if r["svc.counter"][1]["value"].isdigit() else -1 for r in rounds]
    # ---- 0.32b hardening (finding 4)
    cr = counter_ready[0][1] if len(counter_ready) == 1 else {}
    pu = int(cr["pu"]) if cr.get("pu", "").isdigit() else -1
    probe_us = int(cr["us"]) if cr.get("us", "").isdigit() else None
    timing_ok = (cr.get("timing") == "IN_BUDGET") if profile == "0.32b" else (cr.get("timing") is None)
    op_event_ups = [int(m["uptime"]) for l in boot_lines for m in [EVENT_LINE.match(l)] if m and m["uptime"] != "NONE"]
    ev_ups = [int(e["uptime"]) if e["uptime"].isdigit() else -1 for e in events]
    order_pos = [SVC_ORDER.index(d["id"]) if d["id"] in SVC_ORDER else -1
                 for _, d in sorted(skipped + withheld + trans + ready, key=lambda x: x[0])
                 if dumps and _ < dumps[0][0]]

    def round_between_heartbeats(r, at):
        first = min(i for i, _ in r.values())
        before = [int(t["uptime_s"]) for j, t in ticks if j < first]
        after = [int(t["uptime_s"]) for j, t in ticks if j > first]
        lo = (before[-1] * 1000 - TOLERANCE_MS) if before else 0
        hi = (after[0] * 1000 + TOLERANCE_MS) if after else None
        return at >= lo and (hi is None or at < hi)
    reasons = [d["reason"] for _, d in status]
    diags = [m.group(1) for _, l in svc for m in re.finditer(r"\|diag=([A-Z0-9_]+)", l)]
    d0 = dumps[0][1] if len(dumps) == 1 else {}
    items = {
        "operational_reached": op is not None,
        "nothing_before_the_operational_event_printout": bool(svc) and ev_idx is not None and op is not None
                                                          and all(i > ev_idx > op for i, _ in svc),
        "every_service_line_well_formed": not stray,
        "registry_once_in_dependency_order": len(reg) == 1 and reg[0][1]["n"] == str(len(SVC_TABLE))
                                             and reg[0][1]["order"].split(",") == SVC_ORDER
                                             and not any("registry=REFUSED" in l for _, l in svc),
        "adapter_skipped_as_not_installed": [(d["id"], d["kind"]) for _, d in skipped] == [("dev.net0", "ADAPTER")]
                                            and not of(trans, "dev.net0"),
        "counter_running_only_after_readiness": counter_t == [("1", "DECLARED", "STARTING", None), ("2", "STARTING", "RUNNING", None)]
                                                 and len(counter_ready) == 1 and len(t_idx) == 2
                                                 and t_idx[0] < counter_ready[0][0] < t_idx[1]
                                                 and counter_ready[0][1]["pu"] == counter_ready[0][1]["ku"] == counter_ready[0][1]["obs"]
                                                 and counter_ready[0][1]["pu"].isdigit() and int(counter_ready[0][1]["pu"]) >= 1,
        "netmon_withheld_by_adapter": [(d["id"], d["dep"], d["st"]) for _, d in withheld] == [("svc.netmon", "dev.net0", "DECLARED")]
                                      and not of(trans, "svc.netmon"),
        "no_refusal_failure_or_overrun": not any(x in l for _, l in svc for x in ("|refused|", "|to=FAILED", "|overrun|",
                                                 "|unmeasured|", "status_change=", "ready=FAIL", "start=REFUSED")),
        "event_dump_once_after_the_start_phase": len(dumps) == 1 and bool(start_lines) and dumps[0][0] > max(start_lines)
                                                 and (not status or dumps[0][0] < status[0][0]),
        "event_dump_counts_consistent": bool(d0) and ev_recorded is not None and d0["from_seq"] == str(ev_recorded + 1)
                                        and d0["dropped"] == "0" and d0["lost"] == "0" and d0["capacity"] == "32"
                                        and int(d0["recorded"]) == ev_recorded + len(events)
                                        and [int(e["seq"]) for e in events] == list(range(ev_recorded + 1, ev_recorded + 1 + len(events))),
        "event_dump_matches_the_lines": [(e["kind"], e["code"], int(e["arg"], 16)) for e in events]
                                        == [("SERVICE", c, a) for c, a in SVC_EXPECTED_EVENTS],
        "status_rounds_complete_in_table_order": ok_rounds and bool(rounds) and len(status) == len(rounds) * len(SVC_TABLE),
        "status_rounds_every_5_s": bool(rounds) and all(5000 <= g < 5500 for g in gaps) and seen_rounds >= want_rounds,
        "adapter_and_netmon_unavailable_not_installed": bool(rounds) and all(static_ok(r[n][1]) for r in rounds
                                                                             for n in ("dev.net0", "svc.netmon")),
        "counter_available_live_and_fresh": bool(rounds) and all(counter_ok(r, at) for r, at in zip(rounds, times)),
        "counter_value_is_steps_plus_one": bool(rounds) and all(r["svc.counter"][1]["value"].isdigit()
                                                                and int(r["svc.counter"][1]["value"]) == int(r["svc.counter"][1]["steps"]) + pu
                                                                for r in rounds),
        "counter_strictly_increasing": all(b > a for a, b in zip(values, values[1:])) and all(b - a >= 250 for a, b in zip(values, values[1:])),
        "counter_never_above_its_possible_wakes": bool(rounds) and all(wake_bound_ok(r) for r in rounds),
        "compromise_none_known_everywhere": bool(status) and all(d["compromise"] == "NONE_KNOWN" for _, d in status),
        "reasons_appendix_a_or_none_only": len(public) == 27 and bool(reasons) and all(r == "NONE" or r in public for r in reasons),
        "diag_codes_registered": bool(registered) and all(c in registered for c in diags),
        # 0.32b (finding 4): impossible readiness counts
        "readiness_counts_possible": 1 <= pu <= SVC_BUDGET["svc.counter"] and cr.get("ku") == cr.get("pu") == cr.get("obs"),
        # 0.32b (finding 4): duration claims
        "probe_duration_measured_and_in_budget": probe_us is not None and probe_us <= STEP_BUDGET_US and timing_ok,
        "event_times_consistent": bool(ev_ups) and all(u >= 0 for u in ev_ups) and ev_ups == sorted(ev_ups)
                                  and (not op_event_ups or ev_ups[0] >= max(op_event_ups))
                                  and bool(times) and ev_ups[-1] <= times[0],
        "status_rounds_between_their_heartbeats": bool(rounds) and all(round_between_heartbeats(r, at) for r, at in zip(rounds, times)),
        # 0.32b (finding 4): contradictory state reports
        "start_lines_in_dependency_order": bool(order_pos) and -1 not in order_pos and order_pos == sorted(order_pos),
        "round_entries_agree_on_the_time": bool(rounds) and all(r["dev.net0"][1]["at"] == r["svc.netmon"][1]["at"] for r in rounds),
        "status_lines_consistent_with_transitions_mapping_and_clock": bool(status) and not status_contradictions(boot_lines, SVC_INSTALLED),
    }
    return {"pass": all(items.values()), "items": items, "status_rounds": len(rounds), "rounds_required": want_rounds,
            "end_of_capture": {"cut_line": cut_line, "partial_final_round_lines": len(partial)},
            "round_times_ms": times, "counter_values": values, "stray_lines": stray[:8], "service_events": len(events)}


# ---- 0.33 (D-ABR-022): condition C13, the launcher, production expectations ----------------------------------------
APP_TABLE = [("app.counterview", "VIEWER", "1", "NONE", "svc.counter"), ("app.netstatus", "VIEWER", "1", "NONE", "svc.netmon"),
             ("app.browser", "BROWSER", "1", "NONE", "svc.netmon")]  # the closed production table, in AppId order
APP_ORDER = [a[0] for a in APP_TABLE]
APP_REG_OK = re.compile(r"^ABR\|APP\|registry=OK\|entries=(?P<n>\d+)\|order=(?P<order>[a-z0-9.,]+)\|executor=(?P<ex>[A-Z_]+)$")
APP_REG_REFUSED = re.compile(r"^ABR\|APP\|registry=REFUSED\|diag=(?P<diag>[A-Z0-9_]+)\|entry=(?P<entry>\d+)\|executor=(?P<ex>[A-Z_]+)$")
_MISSING = r"[a-z0-9.]+:[A-Z_]+:[A-Z_]+"
APPINFO = re.compile(r"^ABR\|APPINFO\|id=(?P<id>app\.[a-z0-9.]+)\|kind=(?P<kind>[A-Z]+)\|rev=(?P<rev>\d+)\|exec=(?P<exec>[A-Z]+)"
                     r"\|requires=(?P<req>NONE|[a-z0-9.]+(?:,[a-z0-9.]+)*)\|prerequisites=(?P<pre>SATISFIED|UNSATISFIED|NOT_EVALUATED)"
                     r"\|unavailable=(?P<un>NONE|NOT_EVALUATED|" + _MISSING + r"(?:," + _MISSING + r")*)"
                     r"\|observed_at_ms=(?P<at>\d+|NONE)\|clock=(?P<clock>OK|DEGRADED|UNREADABLE)$")
LAUNCH_PREFIXES = ("ABR|LAUNCH|", "ABR|LAUNCHRESULT|", "ABR|LAUNCHPAD|", "ABR|APPQUERY|")
RESERVED_STATES = ("DISPATCHED", "RUNNING", "EXITED", "FAULTED", "LOST")


def execution_claims(lines):
    """Every ABR line that claims or implies that something executed. There must be none in 0.33. A refused transition
    line names its refused target (to=RUNNING) and is not a claim."""
    bad = []
    for l in lines:
        if not l.startswith("ABR|"):
            continue
        launch = l.startswith(("ABR|LAUNCH|", "ABR|LAUNCHRESULT|"))
        if ("executed=YES" in l or re.search(r"\|process=(?!NONE(\||$))", l) or "exec=NATIVE" in l
                or re.search(r"\|executor=(?!ABSENT(\||$))", l) or re.search(r"\|processes=(?!0(\||$))", l)
                or re.search(r"\|executed=(?!0(\||$)|NO(\||$))", l)
                or (launch and "|refused|" not in l
                    and re.search(r"\|(?:state|to)=(?:" + "|".join(RESERVED_STATES) + r")(\||$)", l))):
            bad.append(l)
    return bad


def appinfo_expected(r, req_names):
    """What an APPINFO line must say about prerequisites, given the status round it belongs to."""
    missing = [f"{n}:{r[n][1]['status']}:{r[n][1]['reason']}" for n in req_names if r[n][1]["status"] != "AVAILABLE"]
    return ("SATISFIED", "NONE") if not missing else ("UNSATISFIED", ",".join(missing))


def launcher_rounds(boot_lines):
    """Status rounds (as C12 finds them) with the APPINFO group printed right after each. The final group may be cut
    by the end of capture (nothing printed after it); anything else is reported."""
    status = [(i, m.groupdict()) for i, l in enumerate(boot_lines) for m in [SVC_STATUS.match(l)] if m]
    last_abr = max((i for i, l in enumerate(boot_lines) if l.startswith("ABR|")), default=-1)
    out, used, partial = [], set(), 0
    for k in range(0, len(status), len(SVC_TABLE)):
        g = status[k:k + len(SVC_TABLE)]
        idx = [i for i, _ in g]
        if [d["id"] for _, d in g] != SVC_TABLE or idx != list(range(idx[0], idx[0] + len(idx))):
            break
        r = {d["id"]: (i, d) for i, d in g}
        group = []
        for j in range(idx[-1] + 1, idx[-1] + 1 + len(APP_ORDER)):
            m = APPINFO.match(boot_lines[j]) if j < len(boot_lines) else None
            if not m:
                break
            group.append((j, m.groupdict()))
            used.add(j)
        complete = [d["id"] for _, d in group] == APP_ORDER
        last_line = group[-1][0] if group else idx[-1]
        at_end = not complete and last_line >= last_abr - 1 and k + len(SVC_TABLE) >= len(status)
        if at_end:
            partial = len(group)
        out.append((r, group, complete or at_end))
    return out, used, partial


def judge_launcher(boot_lines):
    """0.33 C13 for one boot (design §11): the application registry and discovery of a production kernel. Every item
    must hold. A production kernel never makes a launch request."""
    op = boot_lines.index(OPERATIONAL) if OPERATIONAL in boot_lines else None
    app = [(i, l) for i, l in enumerate(boot_lines) if l.startswith("ABR|APP")]
    last_abr = max((i for i, l in enumerate(boot_lines) if l.startswith("ABR|")), default=-1)
    cut = None
    if app and app[-1][0] == last_abr and app[-1][1].startswith("ABR|APPINFO|") and not APPINFO.match(app[-1][1]):
        cut = app.pop()[1]
    regs = [(i, m.groupdict()) for i, l in app for m in [APP_REG_OK.match(l)] if m]
    refused = [l for _, l in app if APP_REG_REFUSED.match(l)]
    infos = [(i, m.groupdict()) for i, l in app for m in [APPINFO.match(l)] if m]
    stray = [l for _, l in app if not (APP_REG_OK.match(l) or APP_REG_REFUSED.match(l) or APPINFO.match(l))]
    svc_reg = next((i for i, l in enumerate(boot_lines) if SVC_REGISTRY.match(l)), None)
    first_status = next((i for i, l in enumerate(boot_lines) if SVC_STATUS.match(l)), None)
    rounds, used, partial = launcher_rounds(boot_lines)
    table = {a[0]: a for a in APP_TABLE}

    def time_clock_ok(r, d):
        return d["at"] == r["dev.net0"][1]["at"] and d["clock"] == r["svc.counter"][1]["clock"]

    def prereq_ok(r, d):
        a = table.get(d["id"])
        return a is not None and (d["pre"], d["un"]) == appinfo_expected(r, a[4].split(","))
    grouped = [(r, d) for r, g, _ in rounds for _, d in g]
    items = {
        "application_registry_once_after_the_service_start": len(regs) == 1 and not refused and op is not None
                                                            and svc_reg is not None and first_status is not None
                                                            and op < svc_reg < regs[0][0] < first_status,
        "application_registry_is_the_production_table": len(regs) == 1 and regs[0][1]["n"] == str(len(APP_TABLE))
                                                       and regs[0][1]["order"].split(",") == APP_ORDER
                                                       and regs[0][1]["ex"] == "ABSENT",
        "every_application_line_well_formed": not stray,
        "appinfo_after_every_status_round": bool(rounds) and all(ok for _, _, ok in rounds),
        "no_appinfo_outside_a_round": bool(infos) and all(i in used for i, _ in infos),
        "appinfo_descriptors_match_the_table": bool(infos) and all(
            d["id"] in table and (d["kind"], d["rev"], d["exec"], d["req"]) == table[d["id"]][1:] for _, d in infos),
        "no_application_executable": bool(infos) and all(d["exec"] == "NONE" for _, d in infos)
                                     and all(d["ex"] == "ABSENT" for _, d in regs),
        "appinfo_time_and_clock_of_its_round": bool(grouped) and all(time_clock_ok(r, d) for r, d in grouped),
        "appinfo_prerequisites_consistent_with_its_round": bool(grouped) and all(prereq_ok(r, d) for r, d in grouped),
        "no_launch_request_in_production": not any(l.startswith(LAUNCH_PREFIXES) or "injecting=launch" in l for l in boot_lines),
        "no_execution_claimed": not execution_claims(boot_lines),
        "nothing_before_operational": op is not None and all(i > op for i, _ in app),
    }
    return {"pass": all(items.values()), "items": items, "rounds_with_appinfo": len(rounds),
            "end_of_capture": {"cut_line": cut, "partial_final_group_lines": partial}, "stray_lines": stray[:8]}


def judge_negative(serial_log, host):
    """The staged kernel differs from the hash in limine.conf: no Abraham code may run, and
    Limine must say why. Its exact wording is recorded, not assumed."""
    lines = serial_lines(serial_log)
    entered = any(l.startswith("ABR|") for l in lines)
    refusal = [l for l in lines if re.search(r"hash|mismatch|panic|checksum", l, re.IGNORECASE)]
    held = not entered and bool(refusal)
    return {"verdict": "NEGATIVE_CONTROL_HELD" if held else "NEGATIVE_CONTROL_BROKEN",
            "kernel_code_ran": entered, "loader_refusal_lines": refusal[:8],
            "evidence_label": "VM_MEASURED",
            "not_claimed": "Secure Boot or any protection beyond Limine's own path-hash check"}


def judge_plumbing(serial_log, host):
    lines = serial_lines(serial_log)
    bds = [l for l in lines if l.startswith("BdsDxe:")]
    ok = bool(bds) and host.get("status_before_quit", {}).get("status") == "running" and host.get("qemu_exit") == 0
    return {"verdict": "HARNESS_PLUMBING_OK" if ok else "HARNESS_PLUMBING_FAIL",
            "not_claimed": "No bootloader or kernel was present. This says nothing about Abraham.",
            "firmware_lines": bds[:6], "abraham_lines": [l for l in lines if l.startswith("ABR|")]}


def judge(serial_log, host, args):
    cold = host.get("restart_mode") == "cold"
    lines = serial_lines(serial_log)
    boots = split_boots(lines)
    b1 = boots[0] if boots else []
    if cold:
        lines2 = serial_lines(serial_log.with_name("serial-boot2.log"))
        b2 = split_boots(lines2)[0] if lines2 else []
        lines = lines + lines2
    else:
        b2 = boots[1] if len(boots) > 1 else []
    events = host["qmp_events"] + host.get("qmp_events_boot2", [])
    resets = [e for e in events if e.get("event") == "RESET"]
    guest_resets = [e for e in resets if e.get("data", {}).get("guest")]
    host_resets = [e for e in resets if not e.get("data", {}).get("guest")]
    clean_quit_1 = any(e.get("event") == "SHUTDOWN" and e.get("data", {}).get("reason") == "host-qmp-quit"
                       for e in host["qmp_events"])

    def banner(boot_lines):
        for line in boot_lines:
            match = BANNER.match(line)
            if match:
                return match.groupdict()
        return None

    def loader(boot_lines):
        for line in boot_lines:
            match = LOADER.match(line)
            if match:
                return match.groupdict()
        return None

    def ticks(boot_lines):
        return [int(m["s"]) for m in map(TICK.match, boot_lines) if m]

    # Only a boot option on the virtio boot disk counts; the firmware's built-in shell
    # (an Fv(...) path) is what UEFI starts when no loader was found.
    bds1 = [m.groupdict() for m in map(BDS_START.match, b1) if m and m["path"].startswith("PciRoot(")]
    loader1 = loader(b1)
    banner1, banner2 = banner(b1), banner(b2)
    ticks1, ticks2 = ticks(b1), ticks(b2)
    faults = [l for l in lines if l.startswith("ABR|FAULT")]
    continuous = bool(ticks1) and ticks1 == list(range(ticks1[0], ticks1[0] + len(ticks1)))
    epochs_fresh = (banner1 and banner2 and "UNAVAILABLE" not in (banner1["epoch"], banner2["epoch"])
                    and banner1["epoch"] != banner2["epoch"])

    conditions = {
        "C1_loader": {
            "pass": bool(bds1) and bool(loader1) and loader1["loader"].startswith("Limine")
                    and loader1["rev"] == "true",
            "firmware_started": bds1[:2], "kernel_reported_loader": loader1},
        "C2_kernel_entered": {"pass": ENTRY in b1 and KMAIN in b1,
                              "nasm_entry": ENTRY in b1, "rust_kmain": KMAIN in b1},
        "C3_operational": {"pass": OPERATIONAL in b1 and len(ticks1) >= 1, "first_ticks": ticks1[:3]},
        "C4_banner": {"pass": bool(banner1) and any(HUMAN_BANNER.match(l) for l in b1), "banner": banner1},
        "C5_no_crash": {
            "pass": not faults and not guest_resets and continuous
                    and len(ticks1) >= args.stable_seconds - 2
                    and host.get("status_after_window_1", {}).get("status") == "running",
            "faults": faults, "guest_resets": guest_resets, "ticks_boot1": len(ticks1),
            "ticks_continuous": continuous, "status": host.get("status_after_window_1")},
        "C6_restart": {
            "pass": (clean_quit_1 and host.get("qemu_exit") == 0 and not resets if cold
                     else len(host_resets) == 1 and not guest_resets)
                    and OPERATIONAL in b2 and bool(banner2) and ENTRY in b2
                    and len(ticks2) >= 2 and (epochs_fresh or (banner1 or {}).get("epoch") == "UNAVAILABLE"),
            "mode": "cold (QMP quit, relaunch: same boot disk, same NV variable store)" if cold
                    else "warm (QMP system_reset)",
            "boot1_clean_quit": clean_quit_1, "boot1_qemu_exit": host.get("qemu_exit"),
            "boot2_qemu_exit": host.get("qemu_exit_boot2"), "resets": resets,
            "boot2_entered": ENTRY in b2, "boot2_operational": OPERATIONAL in b2, "banner2": banner2,
            "boot_epoch_fresh": epochs_fresh, "ticks_boot2": len(ticks2)},
        "C7_reproducible": {"pass": None, "note": "judged across runs: abr_boot_001.py series"},
    }
    # 0.31b C0 (F-031a-E01, F-029-05): the configured timer mode must be verified in effect.
    conditions["C0_configuration"] = judge_configuration(host, cold)
    profile = getattr(args, "profile", None)
    if profile in ("0.31a", "0.31b", "0.32", "0.32b", "0.33"):
        expect_memtest = bool(getattr(args, "expect_memtest", False))
        m1, m2 = judge_memory(b1, expect_memtest), judge_memory(b2, expect_memtest)
        conditions["C9_memory_ownership"] = {"pass": m1["pass"] and m2["pass"], "boot1": m1, "boot2": m2,
                                             "expect_memtest": expect_memtest}
    if profile in ("0.31b", "0.32", "0.32b", "0.33"):
        memtest = bool(getattr(args, "expect_memtest", False))
        l1, l2 = judge_lifecycle(b1, memtest), judge_lifecycle(b2, memtest)
        conditions["C10_lifecycle_events"] = {"pass": l1["pass"] and l2["pass"], "boot1": l1, "boot2": l2}
        k1, k2 = judge_clock(b1), judge_clock(b2)
        conditions["C11_clock"] = {"pass": k1["pass"] and k2["pass"], "boot1": k1, "boot2": k2}
    if profile in ("0.32", "0.32b", "0.33"):
        sp = "0.32b" if profile == "0.33" else profile  # 0.33 keeps the 0.32b service contract unchanged
        s1, s2 = judge_services(b1, sp), judge_services(b2, sp)
        conditions["C12_services"] = {"pass": s1["pass"] and s2["pass"], "boot1": s1, "boot2": s2}
    if profile == "0.33":
        a1, a2 = judge_launcher(b1), judge_launcher(b2)
        conditions["C13_launcher"] = {"pass": a1["pass"] and a2["pass"], "boot1": a1, "boot2": a2}
    return {"run_id": args.run_id, "evidence_label": "VM_MEASURED", "conditions": conditions, "profile": profile,
            "boots_observed": len([b for b in boots if ENTRY in b]),
            "not_claimed": ["acceptance (Jadin decides)", "hardware behaviour (HARDWARE_MEASURED)",
                            "any Abraham capability beyond boot, banner, timer and fault reporting"]}


def series(args):
    runs = []
    for run_id in args.run_ids:
        final = EVIDENCE / "ABR-BOOT-001" / run_id / "results.json.final"
        host = EVIDENCE / "ABR-BOOT-001" / run_id / "host.json"
        if not final.is_file():
            raise SystemExit(f"BLOCKED: {final} missing")
        r, h = json.loads(final.read_text()), json.loads(host.read_text())
        runs.append({"run_id": run_id, "verdict": r["verdict"], "accel": h["accelerator"],
                     "kernel_elf": h["inputs"]["kernel_elf"]["sha256"],
                     "limine_efi": h["inputs"]["limine_efi"]["sha256"]})
    info_path = OS / "build" / "build-info.json"
    info = json.loads(info_path.read_text()) if info_path.is_file() else {}
    passing = [r for r in runs if r["verdict"] == "PASS"]
    same_inputs = len({(r["kernel_elf"], r["limine_efi"]) for r in passing}) == 1
    repro_ok = info.get("mode") == "repro" and info.get("result") == "PASS"
    result = {"C7_reproducible": {"pass": len(passing) >= 2 and same_inputs and repro_ok,
                                  "runs": runs, "same_inputs": same_inputs, "build_repro": repro_ok}}
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["C7_reproducible"]["pass"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ("run", "plumbing"):
        p = sub.add_parser(name)
        p.add_argument("--run-id", required=True)
        p.add_argument("--kernel", required=(name == "run"), help="kernel ELF to stage (0.31a: required, no default)")
        p.add_argument("--expect-kernel-sha256", required=(name == "run"),
                       help="0.31a: SHA-256 the kernel must have; any other kernel is refused before the run")
        p.add_argument("--profile", choices=("0.29", "0.31a", "0.31b", "0.32", "0.32b", "0.33"), required=(name == "run"),
                       help="0.29 = C0-C8; 0.31a = C0-C9 (frame ownership); 0.31b = C0-C11 (+ lifecycle/events, clock); "
                            "0.32 = C0-C12 (+ services); 0.32b = C0-C12 with the 0.32b readiness line")
        p.add_argument("--expect-memtest", action="store_true",
                       help="0.31a: the kernel is the diag-mem-exhaust build; C9 requires its PASS summary")
        p.add_argument("--qemu-dir", required=True,
                       help="absolute folder of the pinned QEMU (holds qemu-system-x86_64.exe and share/)")
        p.add_argument("--accel", choices=("whpx", "tcg"), default="whpx")
        p.add_argument("--cpu")
        p.add_argument("--limine-efi")
        p.add_argument("--stable-seconds", type=int, default=15)
        p.add_argument("--boot-timeout", type=int, default=120)
        p.add_argument("--negative-hash", action="store_true",
                       help="negative control: stage a one-byte-altered kernel under the real hash")
        p.add_argument("--negative-wait", type=int, default=40)
        p.add_argument("--stage-defect", choices=("kernel-missing", "config-missing", "bad-kernel-path",
                                                   "tamper-matching-hash"), help="G7 negative test only")
        p.add_argument("--kill-qemu-after-operational", action="store_true", help="G7 fail-closed test only")
        p.add_argument("--no-timer-opt-out", action="store_true",
                       help="control runs only: do not opt QEMU out of Windows timer-resolution throttling")
        p.add_argument("--restart", choices=("cold", "warm"), default="cold",
                       help="C6: cold = QMP quit + relaunch (default); warm = QMP system_reset")
    s = sub.add_parser("series")
    s.add_argument("run_ids", nargs="+")
    args = parser.parse_args()
    if args.mode == "series":
        return series(args)
    return boot(args, plumbing=args.mode == "plumbing")


if __name__ == "__main__":
    raise SystemExit(main())
