"""ABRAHAM VM LAUNCHER 0.33.2: the counted verification campaign (D-ABR-024, D-ABR-025, D-ABR-026 Phase 3).

0.33.2 re-runs every 0.33.1 entry against the 0.33.2 program, with these changes, all fixed before any run:
  P001, P002, P004  a freeze of QEMU alone now ends CLOCK_ANOMALY_CAUSE_NOT_ESTABLISHED (exit 11): the launcher kept
                    running, so the host gives no evidence of the cause (D-ABR-026 3A). P004 is now VERIFIED through
                    the composite judge (3B);
  P006              new: QEMU and the launcher frozen together (a host suspension): exit 0, cause HOST_SUSPENSION;
  F004              new: 3A and F-VML-03 reproduced with the 0.33.1 program on the diag-tsc-jump logs, then corrected;
  F005              new: the composite judge's self-test;
  V001/V002         also vmlauncher-0.33.1 preserved.

(0.33.1's description follows, unchanged.)
ABRAHAM VM LAUNCHER 0.33.1: the counted verification campaign (D-ABR-024, D-ABR-025; record TR-0046).

0.33.1 re-runs every 0.33 entry against the corrected program and adds:
  F001-F003  F-VML-01 reproduced with the 0.33 program, then corrected; no false alarm on 16 genuine logs;
  P001-P005  forced pauses (QEMU frozen with tools/pause_qemu.py) on WHPX, TCG, below the kernel's 5 s limit, on the
             launchpad build, and in a real console window;
  V001/V002  also prove vmlauncher-0.33 (TR-0044, TR-0045 and the owner runs) unchanged.


  python -I -B tools/campaign_vml.py

Every entry's expected outcome is fixed below, in EXPECT, before any counted run. Ids are never reused: the campaign
refuses to start if evidence/campaign-vml exists. The launcher's source, the deployed program and the tools are
frozen (SOURCE_MANIFEST.json) and re-checked after every entry. Each entry records its command, its console, what
was observed, and whether that was as expected. Nothing in work-0.33 or any other tree is written (V001/V002 prove
it). Test fixtures (copies of pinned files, some with one byte changed) live outside OneDrive in a temporary folder,
are described with their digests in the record, and are deleted at the end.
Standard library and ctypes only. Nothing is downloaded.
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

VML = Path(__file__).resolve().parents[1]
HOME = VML.parent
W = HOME / "work-0.33"
EXE = VML / "Abraham-VM-Launcher.exe"
OUT = VML / "evidence" / "campaign-vml"
RUNS = OUT / "runs"
MENU_RUNS = OUT / "menu-runs"
QDIR = Path.home() / "abraham-toolchain" / "qemu" / "11.1.0-weil-20260811"
QEXE = QDIR / "qemu-system-x86_64.exe"
PY = sys.executable
P = "VML-0.33.2-"
OLD = HOME / "vmlauncher-0.33"
OLD1 = HOME / "vmlauncher-0.33.1"
OLD1_EXE = OLD1 / "Abraham-VM-Launcher.exe"
OLD_EXE = OLD / "Abraham-VM-Launcher.exe"
STANDBY = OLD / "runs" / "VML-20261109T201841Z" / "serial.log"

# ---- expected outcomes, fixed before the campaign -------------------------------------------------------------------
EXPECT = {
    "V001": "before the campaign: the TR-0042 index holds (DECISIONS.md append-only); the vmlauncher-0.33 index (559) and "
            "the vmlauncher-0.33.1 index (585) hold, each with its DECISIONS.md row an earlier state of the append-only "
            "file; both launcher packages match their .sha256; full-tree snapshots of work-0.33, vmlauncher-0.33 and "
            "vmlauncher-0.33.1 taken",
    "H001": "cargo test --release --offline: 20 passed, 0 failed",
    "F001": "F-VML-01 reproduced first: the 0.33 program's live checks on the TR-0045 standby log fail heartbeat_continuous "
            "and services_as_designed_every_round (the defect)",
    "F002": "the 0.33.2 program on the same log: every boot and service check true, contract CONSISTENT, one clock gap "
            "3318 -> 3570 (251 s) reported by the kernel, clock DEGRADED (TSC_FORWARD_JUMP)",
    "F003": "no false alarm: the 0.33.2 live checks on 16 genuine logs (6 owner runs, 0.33 A001/A004/A005/A006, harness "
            "W001/W002/T001/T002/L001/L002): all checks true; contract CONSISTENT (NOT REACHED for early-fail); exit 0",
    "F004": "3A and F-VML-03 reproduced first: on the diag-tsc-jump logs O003 and O004 (a jump injected inside the guest, "
            "no host pause) the 0.33.1 program reports a 'host pause' and a services problem (round spacing). The 0.33.2 "
            "program reports a clock gap 3 -> 3603 with no 'host pause' wording, every service check true, CONSISTENT",
    "F005": "the composite judge's self-test on TR-0046's P004 log (with L001 and O003 as non-vacuity sources): 9/9 correct",
    "P001": "production WHPX, QEMU alone frozen 30 s at 10 s after OPERATIONAL: one clock gap the kernel reported (25-35 s "
            "skipped), cause NOT_ESTABLISHED (the launcher kept running); clock DEGRADED; boot PASS; services AS DESIGNED; "
            "contract CONSISTENT; exit 11 CLOCK_ANOMALY_CAUSE_NOT_ESTABLISHED; VERIFIED through launch_probe degraded-clock",
    "P002": "the same on TCG: exit 11; cause NOT_ESTABLISHED; VERIFIED through launch_probe degraded-clock",
    "P003": "production WHPX, QEMU frozen 4 s right after the third status round (below the kernel's 5 s limit): no "
            "clock anomaly; boot PASS; services PROBLEMS naming the counter's progress under 250; contract CONSISTENT; "
            "exit 10 SERVICES_NOT_AS_DESIGNED; VERIFIED (official C12 fails too: agreement)",
    "P004": "launchpad WHPX, QEMU alone frozen 30 s: exit 11; cause NOT_ESTABLISHED; VERIFIED through the composite "
            "judge (launch_probe launchpad + degraded-clock rules), with agreement on boot, services and contract",
    "P005": "a real console window, production, QEMU alone frozen 30 s: the panel shows the clock gap and its cause not "
            "established, clock DEGRADED, not a failure; Q; probe PASS; VERIFIED",
    "P006": "production WHPX, QEMU and the launcher frozen together 30 s (a host suspension): one clock gap, cause "
            "HOST_SUSPENSION with the launcher stopped 25-40 s; boot PASS; services AS DESIGNED; CONSISTENT; exit 0 OK; VERIFIED",
    "B001": "two clean builds in new target folders are byte-identical to the deployed program",
    "S001": "Cargo.lock has no dependency; PE32+ AMD64 console, no manifest (no elevation); system DLL imports only; "
            "no forbidden call in the source (registry write, PATH, bcdedit, runas, http); sockets only on 127.0.0.1; "
            "every file write goes into the run folder",
    "X001": "live checks on the 45 J007 falsified logs: the 2 genuine controls CONSISTENT (exit 0); "
            "the other 43 INCONSISTENT (exit 6)",
    "A001": "production WHPX, stop 20 s after OPERATIONAL: exit 0 OK; verify_run VERIFIED",
    "A002": "production WHPX again, same program, no rebuild or reconfiguration: exit 0; VERIFIED",
    "A003": "production WHPX a third time: exit 0; VERIFIED",
    "A004": "launchpad WHPX: exit 0; CONSISTENT (17 of 17); VERIFIED (launch_probe launchpad PASS)",
    "A005": "production TCG: exit 0; VERIFIED",
    "A006": "launchpad TCG: exit 0; VERIFIED",
    "A007": "real console window (conhost), production, Q typed into the window after 20 s: probe PASS "
            "(panel shows OPERATIONAL, clean, sealed, waits for a key, no QEMU left); VERIFIED",
    "A008": "real console window, production, the window closed (WM_CLOSE) after 20 s: probe PASS "
            "(clean QMP quit inside the close-event time, sealed, no QEMU left); VERIFIED",
    "A009": "real console window started with no kernel and no run id: menu shown, key 1, Q after 20 s: probe PASS; VERIFIED",
    "A010": "plain output, Q sent through redirected standard input 20 s after OPERATIONAL: exit 0, "
            "requested_by 'the operator pressed Q'; VERIFIED",
    "N001": "missing QEMU installation (--qemu-dir that does not exist): exit 3; QEMU executable, firmware code and "
            "variable template MISSING; QEMU never started; sealed",
    "N002": "missing kernel (fixture home without it): exit 3; kernel ELF MISSING, the rest OK; nothing started",
    "N003": "missing firmware (fixture QEMU folder without edk2-x86_64-code.fd): exit 3; firmware code MISSING; nothing started",
    "N004": "wrong kernel digest (one byte changed): exit 2; kernel ELF DIGEST MISMATCH; nothing started",
    "N005": "wrong Limine EFI digest: exit 2; Limine DIGEST MISMATCH; nothing started",
    "N006": "wrong QEMU executable digest: exit 2; QEMU executable DIGEST MISMATCH; nothing started",
    "N007": "wrong firmware digest: exit 2; firmware code DIGEST MISMATCH; nothing started",
    "N008": "boot-entry template changed (its path line): exit 2; limine.conf DIGEST MISMATCH; nothing started",
    "N009": "failed boot by an injected fault (early-fail, WHPX): exit 1; FAILED AS DESIGNED; contract NOT REACHED; "
            "clean shutdown; VERIFIED (the fault probe's early rules, CPU halted)",
    "N010": "failed boot by the time limit (production WHPX, --boot-timeout 1): exit 1; kernel boot FAILED naming the "
            "1 s limit; clean shutdown; no QEMU left; sealed",
    "N011": "duplicate launcher: while N011 runs, N011b is refused with exit 4 (another launcher) and starts no "
            "second QEMU; N011 ends exit 0 and is VERIFIED",
    "N012": "a QEMU of the pinned toolchain already running (started by the campaign, paused, no disk): exit 4 "
            "naming its pid; nothing started; that QEMU is then stopped by the campaign",
    "N013": "QEMU killed 5 s after OPERATIONAL: exit 5 VM_TERMINATED_UNEXPECTEDLY; shutdown mode "
            "QEMU_EXITED_UNEXPECTEDLY; sealed; no QEMU left",
    "N014": "QEMU killed before OPERATIONAL: exit 5; never OPERATIONAL; boot FAILED; sealed; no QEMU left",
    "N015": "the launcher killed 5 s after OPERATIONAL: its QEMU is gone within 5 s (kill-on-close job); "
            "the run folder is left unsealed",
    "N016": "the next launch lists N015 (only) as never sealed and leaves it as it was: exit 0; VERIFIED",
    "N017": "a reused run id (A001): exit 7; nothing started; A001's folder unchanged",
    "X002": "on every VM run with an official (or, for P004, composite) judgment, the live verdicts agree (at least 18 runs)",
    "X003": "the boot disk staged by A001 (production) and A004 (launchpad) is byte-identical to the counted harness "
            "runs W001 and L001 (kernel, Limine EFI, limine.conf)",
    "V002": "after the campaign: every index and package holds as in V001; the three full-tree snapshots are identical",
}

# ---- helpers --------------------------------------------------------------------------------------------------------


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PE32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.OpenProcess.restype = wintypes.HANDLE


def procs():
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    e = PE32()
    e.dwSize = ctypes.sizeof(PE32)
    out = []
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out.append((e.th32ProcessID, e.szExeFile))
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def image(pid):
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    buf = ctypes.create_unicode_buffer(1024)
    n = wintypes.DWORD(1024)
    ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
    k32.CloseHandle(h)
    return buf.value if ok else None


def qemu_pids(pinned_only=True):
    out = []
    for pid, name in procs():
        if name.lower().startswith("qemu-system"):
            img = image(pid) or ""
            if not pinned_only or img.lower() == str(QEXE).lower():
                out.append(pid)
    return out


def tree_snapshot(root):
    """(relative path -> (size, mtime_ns)) for every file of a tree."""
    snap = {}
    for dirpath, _, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            st = p.stat()
            snap[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


def index_check():
    """The TR-0042 index: `<sha256>  <category>  <path relative to the Abraham home>`. Returns (rows, mismatches,
    the append-only check of DECISIONS.md)."""
    rows = [l.split(None, 2) for l in (W / "EVIDENCE_INDEX_0.33.sha256").read_text().splitlines() if l.strip()]
    bad, decisions = [], None
    for d, cat, rel in rows:
        p = HOME / rel.strip()
        if p.is_file() and sha(p) == d:
            continue
        if cat == "decisions" and p.is_file():
            b = p.read_bytes()
            cut = b.find(b"\n| D-ABR-024 |")
            decisions = {"indexed": d, "current": sha(p),
                         "without_D-ABR-024": hashlib.sha256(b[:cut + 1]).hexdigest() if cut > 0 else None,
                         "rows_after_the_indexed_content": b[cut + 1:].count(b"| D-ABR-") if cut > 0 else None}
            decisions["append_only"] = decisions["without_D-ABR-024"] == d
            continue
        bad.append(f"{cat} {rel.strip()}")
    return len(rows), bad, decisions


def launcher(args, entry, timeout=180, stdin=subprocess.DEVNULL):
    cmd = [str(EXE), *args, "--plain", "--no-wait"]
    with open(OUT / f"{P}{entry}.console.txt", "wb") as f:
        r = subprocess.run(cmd, stdin=stdin, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    return cmd, r.returncode


def launcher_bg(args, entry):
    cmd = [str(EXE), *args, "--plain", "--no-wait"]
    f = open(OUT / f"{P}{entry}.console.txt", "wb")
    return cmd, subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=f, stderr=subprocess.STDOUT), f


def verify(run, entry):
    out = OUT / f"{P}{entry}.verify.json"
    r = subprocess.run([PY, "-I", "-B", str(VML / "tools" / "verify_run.py"), str(run), "--out", str(out)],
                       capture_output=True, text=True)
    return json.loads(out.read_text()) if out.is_file() else {"verdict": "NO OUTPUT", "stderr": r.stderr[-2000:]}


def rec(run):
    p = Path(run) / "launch.json"
    return json.loads(p.read_text()) if p.is_file() else {}


def wait_serial(run, needle=b"ABR|STATE|OPERATIONAL", timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        p = Path(run) / "serial.log"
        if p.is_file() and needle in p.read_bytes():
            return True
        time.sleep(0.1)
    return False


def wait_file(p, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if Path(p).is_file():
            try:
                return json.loads(Path(p).read_text())
            except ValueError:
                pass
        time.sleep(0.05)
    return None


def kill(pid):
    return subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, text=True).returncode


def run_args(entry, kernel="production", accel="whpx", stop=20, extra=()):
    return ["--kernel", kernel, "--accel", accel, "--run-id", P + entry, "--runs-dir", str(RUNS),
            "--auto-stop-after", str(stop), *extra]


def inputs_status(r):
    return {i["name"]: i["status"] for i in r.get("inputs", [])}


# ---- the source freeze ----------------------------------------------------------------------------------------------

FROZEN = ["Cargo.toml", "Cargo.lock", ".cargo/config.toml", "Abraham-VM-Launcher.exe", "README.md",
          "docs/VM_LAUNCHER_DESIGN.md", "tools/verify_run.py", "tools/console_probe.py", "tools/campaign_vml.py",
          "tools/pause_qemu.py", "tools/pause_host.py", "tools/judge_launchpad_degraded.py"]


def source_manifest():
    files = sorted({*FROZEN, *(p.relative_to(VML).as_posix() for p in (VML / "src").glob("*.rs"))})
    return {f: sha(VML / f) for f in files}


# ---- entries --------------------------------------------------------------------------------------------------------


def prefix_of(p, digest):
    b = p.read_bytes()
    for e in [i + 1 for i, c in enumerate(b) if c == 10]:
        if hashlib.sha256(b[:e]).hexdigest() == digest:
            return e
    return None


def launcher_tree_check(tree, index, zipname):
    """A preserved launcher tree: its index (DECISIONS.md may only have grown since), and its package."""
    rows = [l.split("  ", 1) for l in (tree / index).read_text().splitlines() if l.strip()]
    bad, dec = [], None
    for d, rel in rows:
        p = (tree / rel).resolve()
        if p.is_file() and sha(p) == d:
            continue
        if rel == "../DECISIONS.md" and p.is_file():
            dec = {"indexed": d, "indexed_bytes": prefix_of(p, d)}
            dec["append_only"] = dec["indexed_bytes"] is not None
            continue
        bad.append(rel)
    z = tree / "evidence" / "review" / zipname
    zip_ok = (z.with_name(z.name + ".sha256").read_text().split()[0] == sha(z))
    return len(rows), bad, dec, zip_ok


def old_tree_check():
    return launcher_tree_check(OLD, "EVIDENCE_INDEX_VML_0.33.sha256", "ABRAHAM_0.33_VM_LAUNCHER_AUDIT.zip")


def old1_tree_check():
    return launcher_tree_check(OLD1, "EVIDENCE_INDEX_VML_0.33.1.sha256", "ABRAHAM_0.33.1_VM_LAUNCHER_AUDIT.zip")


def e_V001(ctx):
    n, bad, dec = index_check()
    ctx["snapshot"] = tree_snapshot(W)
    ctx["old_snapshot"] = tree_snapshot(OLD)
    ctx["old1_snapshot"] = tree_snapshot(OLD1)
    (OUT / "work-0.33.snapshot-before.json").write_text(json.dumps(ctx["snapshot"], sort_keys=True))
    (OUT / "vmlauncher-0.33.snapshot-before.json").write_text(json.dumps(ctx["old_snapshot"], sort_keys=True))
    n2, bad2, dec2, zip_ok = old_tree_check()
    n3, bad3, dec3, zip3 = old1_tree_check()
    obs = {"index_rows": n, "mismatched": bad, "decisions_md": dec, "files_in_tree": len(ctx["snapshot"]),
           "vml033_index_rows": n2, "vml033_mismatched": bad2, "vml033_decisions_md": dec2, "vml033_package_ok": zip_ok,
           "vml033_files": len(ctx["old_snapshot"]), "vml0331_index_rows": n3, "vml0331_mismatched": bad3,
           "vml0331_decisions_md": dec3, "vml0331_package_ok": zip3, "vml0331_files": len(ctx["old1_snapshot"])}
    return obs, (n == 632 and not bad and bool(dec) and dec["append_only"] and n2 == 559 and not bad2 and bool(dec2)
                 and dec2["append_only"] and zip_ok and n3 == 585 and not bad3 and bool(dec3) and dec3["append_only"] and zip3)


def e_H001(ctx):
    r = subprocess.run(["cargo", "test", "--release", "--offline"], cwd=VML, capture_output=True, text=True, timeout=600)
    (OUT / f"{P}H001.console.txt").write_text(r.stdout + r.stderr)
    m = re.search(r"test result: (\w+)\. (\d+) passed; (\d+) failed", r.stdout)
    obs = {"exit": r.returncode, "summary": m.group(0) if m else None}
    return obs, bool(m) and m.group(1) == "ok" and m.group(2) == "20" and m.group(3) == "0"


def e_B001(ctx):
    digs = []
    for n in (1, 2):
        d = Path(tempfile.mkdtemp(prefix=f"vml-b001-{n}-"))
        r = subprocess.run(["cargo", "build", "--release", "--offline", "--target-dir", str(d)], cwd=VML,
                           capture_output=True, text=True, timeout=900)
        digs.append(sha(d / "release" / "Abraham-VM-Launcher.exe") if r.returncode == 0 else f"BUILD FAILED {r.returncode}")
        shutil.rmtree(d, ignore_errors=True)
    obs = {"build_1": digs[0], "build_2": digs[1], "deployed": sha(EXE)}
    return obs, digs[0] == digs[1] == obs["deployed"]


SYSTEM_DLLS = {"kernel32.dll", "advapi32.dll", "ntdll.dll", "ws2_32.dll", "dbghelp.dll",
               "api-ms-win-core-synch-l1-2-0.dll"}


def e_S001(ctx):
    lock = (VML / "Cargo.lock").read_text()
    packages = re.findall(r'^\[\[package\]\]\s*\nname = "([^"]+)"', lock, re.M)
    b = EXE.read_bytes()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    machine = struct.unpack_from("<H", b, pe + 4)[0]
    magic = struct.unpack_from("<H", b, pe + 24)[0]
    subsystem = struct.unpack_from("<H", b, pe + 24 + 68)[0]
    dlls = sorted({m.decode().lower() for m in re.findall(rb"[A-Za-z0-9_\-]+\.dll", b)})
    src = {p.name: p.read_text(encoding="utf-8") for p in sorted((VML / "src").glob("*.rs"))}
    forbidden = ["RegSetValue", "RegCreateKey", "RegDeleteKey", "SetEnvironmentVariable", "bcdedit", "runas",
                 "http://", "https://", "ShellExecute", "AdjustTokenPrivileges", "SetSystemTime"]
    hits = [(n, w) for n, t in src.items() for w in forbidden if w in t]
    addrs = [(n, l.strip()) for n, t in src.items() for l in t.splitlines()
             if re.search(r"TcpStream::connect|TcpListener::bind|SocketAddr", l)]
    # connect_timeout(&addr, ...) is allowed only because the file's one `addr` is built from 127.0.0.1.
    addr_defs = [l for n, t in src.items() for l in t.splitlines() if re.search(r"let addr\b", l)]
    nonlocal_addr = [a for a in addrs if not re.search(r"127\.0\.0\.1|\[127, 0, 0, 1\]|use std::net", a[1])
                     and not (re.search(r"connect_timeout\(&addr,", a[1]) and addr_defs
                              and all("[127, 0, 0, 1]" in d for d in addr_defs))]
    writes = [(n, i + 1, l.strip()) for n, t in src.items() for i, l in enumerate(t.splitlines())
              if re.search(r"fs::write\(|File::create\(|create_dir(_all)?\(", l) and not l.strip().startswith("//")]
    allowed = re.compile(r"self\.dir|\bdir\b|\brun\b|\bruns\b|log_path|esp\.join|run\.join|dir\.join|\bpath\b")
    bad_writes = [w for w in writes if not allowed.search(w[2])]
    obs = {"cargo_lock_packages": packages, "pe_machine": hex(machine), "pe_magic": hex(magic), "pe_subsystem": subsystem,
           "manifest_present": b"requestedExecutionLevel" in b, "imported_dlls": dlls,
           "forbidden_hits": hits, "socket_lines": addrs, "addr_definitions": addr_defs, "non_local_socket_lines": nonlocal_addr,
           "write_sites": writes, "write_sites_outside_the_run_folder": bad_writes,
           "note": "text and byte scans (limits as 0.33 S004); the write sites are listed for review"}
    ok = (packages == ["abraham-vm-launcher"] and machine == 0x8664 and magic == 0x20B and subsystem == 3
          and not obs["manifest_present"] and set(dlls) <= SYSTEM_DLLS and not hits and not nonlocal_addr and not bad_writes)
    return obs, ok


def e_X001(ctx):
    base = W / "evidence" / "g033" / "ABR-0.33-J007"
    rows = []
    for grp in ("production", "launchpad", "refused"):
        for d in sorted(p for p in (base / grp).iterdir() if p.is_dir()):
            k = "launchpad" if grp == "launchpad" else "production"
            r = subprocess.run([str(EXE), "--check-serial", str(d / "serial.log"), "--kernel", k], capture_output=True, text=True)
            try:
                v = json.loads(r.stdout)["launcher_contract"]
            except (ValueError, KeyError):
                v = "UNPARSED"
            control = d.name == "control_unmutated" and grp != "refused"
            want = ("CONSISTENT", 0) if control else ("INCONSISTENT", 6)
            rows.append({"case": f"{grp}/{d.name}", "expectation": k, "contract": v, "exit": r.returncode,
                         "as_expected": (v, r.returncode) == want})
    (OUT / f"{P}X001.cases.json").write_text(json.dumps(rows, indent=1) + "\n")
    wrong = [r["case"] for r in rows if not r["as_expected"]]
    return {"cases": len(rows), "wrong": wrong,
            "consistent": [r["case"] for r in rows if r["contract"] == "CONSISTENT"]}, len(rows) == 45 and not wrong


def vm_ok(entry, args, want_exit=0, want_result="OK", **_):
    cmd, code = launcher(args, entry)
    run = RUNS / (P + entry)
    v = verify(run, entry)
    r = rec(run)
    obs = {"command": cmd, "exit": code, "result": r.get("result"), "verdicts": r.get("verdicts"),
           "verify": v.get("verdict"), "verify_failed": [k for k, x in v.get("checks", {}).items() if not x],
           "exe_sha256": r.get("launcher", {}).get("exe_sha256")}
    ok = code == want_exit and r.get("result") == want_result and v.get("verdict") == "VERIFIED"
    return obs, ok


def e_A001(ctx):
    return vm_ok("A001", run_args("A001"))


def e_A002(ctx):
    return vm_ok("A002", run_args("A002"))


def e_A003(ctx):
    obs, ok = vm_ok("A003", run_args("A003"))
    same = {rec(RUNS / (P + e)).get("launcher", {}).get("exe_sha256") for e in ("A001", "A002", "A003")}
    obs["same_program_for_A001_to_A003"] = len(same) == 1 and sha(EXE) in same
    return obs, ok and obs["same_program_for_A001_to_A003"]


def e_A004(ctx):
    obs, ok = vm_ok("A004", run_args("A004", kernel="launchpad"))
    return obs, ok and (obs["verdicts"] or {}).get("launcher_contract") == "CONSISTENT"


def e_A005(ctx):
    return vm_ok("A005", run_args("A005", accel="tcg"))


def e_A006(ctx):
    return vm_ok("A006", run_args("A006", kernel="launchpad", accel="tcg"))


def probe(entry, args):
    out = OUT / f"{P}{entry}.probe.json"
    cmd = [PY, "-I", "-B", str(VML / "tools" / "console_probe.py"), *args, "--out", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    (OUT / f"{P}{entry}.console.txt").write_text(r.stdout + r.stderr)
    return cmd, (json.loads(out.read_text()) if out.is_file() else {"verdict": "NO OUTPUT"})


def e_A007(ctx):
    cmd, p = probe("A007", ["--run-id", P + "A007", "--runs-dir", str(RUNS), "--kernel", "production",
                            "--action", "key-q", "--hold", "20"])
    v = verify(RUNS / (P + "A007"), "A007")
    obs = {"command": cmd, "probe": p.get("verdict"), "verify": v.get("verdict"),
           "requested_by": (p.get("shutdown") or {}).get("requested_by")}
    return obs, p.get("verdict") == "PASS" and v.get("verdict") == "VERIFIED"


def e_A008(ctx):
    cmd, p = probe("A008", ["--run-id", P + "A008", "--runs-dir", str(RUNS), "--kernel", "production",
                            "--action", "close-window", "--hold", "20"])
    v = verify(RUNS / (P + "A008"), "A008")
    obs = {"command": cmd, "probe": p.get("verdict"), "verify": v.get("verdict"),
           "requested_by": (p.get("shutdown") or {}).get("requested_by")}
    return obs, p.get("verdict") == "PASS" and v.get("verdict") == "VERIFIED" \
        and obs["requested_by"] == "the launcher window was closed"


def e_A009(ctx):
    cmd, p = probe("A009", ["--menu-key", "1", "--run-id", P + "A009", "--runs-dir", str(MENU_RUNS),
                            "--action", "key-q", "--hold", "20"])
    run = MENU_RUNS / str(p.get("run_folder_created_by_the_launcher"))
    v = verify(run, "A009")
    obs = {"command": cmd, "probe": p.get("verdict"), "run_folder": run.name, "verify": v.get("verdict"),
           "kernel": rec(run).get("selected_kernel", {}).get("key")}
    return obs, p.get("verdict") == "PASS" and v.get("verdict") == "VERIFIED" and obs["kernel"] == "production"


def e_A010(ctx):
    args = run_args("A010", stop=120)
    cmd, proc, f = launcher_bg(args, "A010")
    run = RUNS / (P + "A010")
    op = wait_serial(run)
    time.sleep(20)
    proc.stdin.write(b"q")
    proc.stdin.flush()
    code = proc.wait(timeout=60)
    f.close()
    v = verify(run, "A010")
    r = rec(run)
    obs = {"command": cmd, "operational_seen": op, "exit": code, "result": r.get("result"),
           "requested_by": r.get("shutdown", {}).get("requested_by"), "verify": v.get("verdict")}
    return obs, code == 0 and obs["requested_by"] == "the operator pressed Q" and v.get("verdict") == "VERIFIED"


def refused(entry, args, want_exit, want_status):
    before = qemu_pids(pinned_only=False)
    cmd, code = launcher(args, entry)
    after = qemu_pids(pinned_only=False)
    run = RUNS / (P + entry)
    r = rec(run)
    v = verify(run, entry)
    st = inputs_status(r)
    obs = {"command": cmd, "exit": code, "result": r.get("result"), "inputs": st,
           "qemu_started": "qemu_command" in r or (run / "serial.log").exists(),
           "qemu_processes_before_after": [before, after], "verify": v.get("verdict")}
    ok = code == want_exit and all(st.get(k) == s for k, s in want_status.items()) and not obs["qemu_started"] \
        and v.get("verdict") == "VERIFIED" and set(after) <= set(before)
    return obs, ok


def fixture_home(ctx, name, mutate=None, drop=None):
    root = ctx["fixtures"] / name
    for rel in (r"work-0.33\build\abraham-kernel-0.33.0-dev.elf",
                r"work-0.33\third_party\limine-12.9.6\extracted\limine-binary\BOOTX64.EFI",
                r"work-0.33\boot\limine.conf"):
        if drop and rel.endswith(drop):
            continue
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HOME / rel, dst)
        if mutate and rel.endswith(mutate[0]):
            mutate[1](dst)
    ctx["fixture_digests"][name] = {p.relative_to(root).as_posix(): sha(p) for p in root.rglob("*") if p.is_file()}
    return root


def fixture_qemu(ctx, name, mutate=None, drop=None):
    root = ctx["fixtures"] / name
    for rel in ("qemu-system-x86_64.exe", r"share\edk2-x86_64-code.fd", r"share\edk2-i386-vars.fd"):
        if drop and rel.endswith(drop):
            continue
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(QDIR / rel, dst)
        if mutate and rel.endswith(mutate[0]):
            mutate[1](dst)
    ctx["fixture_digests"][name] = {p.relative_to(root).as_posix(): sha(p) for p in root.rglob("*") if p.is_file()}
    return root


def flip_last(p):
    b = bytearray(Path(p).read_bytes())
    b[-1] ^= 0xFF
    Path(p).write_bytes(bytes(b))


def flip_middle(p):
    b = bytearray(Path(p).read_bytes())
    b[len(b) // 2] ^= 0xFF
    Path(p).write_bytes(bytes(b))


def change_path_line(p):
    t = Path(p).read_text(encoding="ascii").replace("boot():/boot/abraham-kernel#", "boot():/boot/other-kernel#")
    Path(p).write_text(t, encoding="ascii", newline="\n")


def e_N001(ctx):
    missing = ctx["fixtures"] / "no-such-qemu-folder"
    return refused("N001", run_args("N001", extra=("--qemu-dir", str(missing))), 3,
                   {"QEMU executable": "MISSING", "UEFI firmware code (edk2)": "MISSING",
                    "UEFI variable store template (edk2)": "MISSING", "kernel ELF": "OK"})


def e_N002(ctx):
    home = fixture_home(ctx, "home-without-kernel", drop="abraham-kernel-0.33.0-dev.elf")
    return refused("N002", run_args("N002", extra=("--home", str(home))), 3,
                   {"kernel ELF": "MISSING", "Limine 12.9.6 BOOTX64.EFI": "OK", "QEMU executable": "OK"})


def e_N003(ctx):
    q = fixture_qemu(ctx, "qemu-without-firmware", drop="edk2-x86_64-code.fd")
    return refused("N003", run_args("N003", extra=("--qemu-dir", str(q))), 3,
                   {"UEFI firmware code (edk2)": "MISSING", "QEMU executable": "OK"})


def e_N004(ctx):
    home = fixture_home(ctx, "home-kernel-changed", mutate=("abraham-kernel-0.33.0-dev.elf", flip_last))
    return refused("N004", run_args("N004", extra=("--home", str(home))), 2, {"kernel ELF": "DIGEST MISMATCH"})


def e_N005(ctx):
    home = fixture_home(ctx, "home-limine-changed", mutate=("BOOTX64.EFI", flip_middle))
    return refused("N005", run_args("N005", extra=("--home", str(home))), 2,
                   {"Limine 12.9.6 BOOTX64.EFI": "DIGEST MISMATCH", "kernel ELF": "OK"})


def e_N006(ctx):
    q = fixture_qemu(ctx, "qemu-exe-changed", mutate=("qemu-system-x86_64.exe", flip_middle))
    return refused("N006", run_args("N006", extra=("--qemu-dir", str(q))), 2,
                   {"QEMU executable": "DIGEST MISMATCH", "UEFI firmware code (edk2)": "OK"})


def e_N007(ctx):
    q = fixture_qemu(ctx, "qemu-firmware-changed", mutate=("edk2-x86_64-code.fd", flip_middle))
    return refused("N007", run_args("N007", extra=("--qemu-dir", str(q))), 2,
                   {"UEFI firmware code (edk2)": "DIGEST MISMATCH", "QEMU executable": "OK"})


def e_N008(ctx):
    home = fixture_home(ctx, "home-template-changed", mutate=("limine.conf", change_path_line))
    return refused("N008", run_args("N008", extra=("--home", str(home))), 2,
                   {"Limine boot-entry template limine.conf": "DIGEST MISMATCH"})


def e_N009(ctx):
    obs, ok = vm_ok("N009", run_args("N009", kernel="early-fail", stop=5), want_exit=1, want_result="BOOT_FAILED")
    v = obs["verdicts"] or {}
    return obs, ok and v.get("kernel_boot") == "FAILED AS DESIGNED" and v.get("launcher_contract") == "NOT REACHED"


def e_N010(ctx):
    cmd, code = launcher(run_args("N010", stop=3, extra=("--boot-timeout", "1")), "N010")
    run = RUNS / (P + "N010")
    r = rec(run)
    v = verify(run, "N010")
    vd = r.get("verdicts", {})
    sh = r.get("shutdown", {})
    obs = {"command": cmd, "exit": code, "result": r.get("result"), "kernel_boot": vd.get("kernel_boot"),
           "detail": vd.get("kernel_boot_detail"), "shutdown": sh.get("mode"), "verify": v.get("verdict"),
           "qemu_left": qemu_pids()}
    ok = code == 1 and r.get("result") == "BOOT_FAILED" and vd.get("kernel_boot") == "FAILED" \
        and "1 s" in (vd.get("kernel_boot_detail") or "") and sh.get("mode") == "CLEAN_QMP_QUIT" \
        and v.get("verdict") == "VERIFIED" and not obs["qemu_left"]
    return obs, ok


def e_N011(ctx):
    cmd_a, pa, fa = launcher_bg(run_args("N011", stop=25), "N011")
    run_a = RUNS / (P + "N011")
    op = wait_serial(run_a)
    during = qemu_pids()
    cmd_b, code_b = launcher(run_args("N011b", stop=5), "N011b")
    during2 = qemu_pids()
    code_a = pa.wait(timeout=120)
    fa.close()
    rb = rec(RUNS / (P + "N011b"))
    va = verify(run_a, "N011")
    vb = verify(RUNS / (P + "N011b"), "N011b")
    obs = {"commands": [cmd_a, cmd_b], "operational_seen": op, "pinned_qemu_during": [during, during2],
           "exit_a": code_a, "exit_b": code_b, "result_b": rb.get("result"),
           "b_saw_another_launcher": rb.get("duplicate_check", {}).get("another_launcher_running"),
           "verify_a": va.get("verdict"), "verify_b": vb.get("verdict")}
    ok = op and code_b == 4 and obs["b_saw_another_launcher"] is True and len(during) == 1 and during == during2 \
        and code_a == 0 and va.get("verdict") == "VERIFIED" and vb.get("verdict") == "VERIFIED"
    return obs, ok


def e_N012(ctx):
    q = subprocess.Popen([str(QEXE), "-machine", "q35", "-accel", "tcg", "-display", "none", "-nodefaults",
                          "-nic", "none", "-S"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=0x08000000)
    time.sleep(2.0)
    pinned = qemu_pids()
    try:
        cmd, code = launcher(run_args("N012"), "N012")
    finally:
        q.kill()
        q.wait(timeout=20)
    r = rec(RUNS / (P + "N012"))
    v = verify(RUNS / (P + "N012"), "N012")
    listed = r.get("duplicate_check", {}).get("pinned_qemu_processes_running", [])
    obs = {"command": cmd, "campaign_qemu_pid": q.pid, "pinned_running_before": pinned, "exit": code,
           "result": r.get("result"), "listed": listed, "verify": v.get("verdict"), "qemu_left": qemu_pids()}
    ok = code == 4 and any(f"pid {q.pid} " in x for x in listed) and "qemu_command" not in r \
        and v.get("verdict") == "VERIFIED" and not obs["qemu_left"]
    return obs, ok


def e_N013(ctx):
    cmd, p, f = launcher_bg(run_args("N013", stop=90), "N013")
    run = RUNS / (P + "N013")
    op = wait_serial(run)
    time.sleep(5)
    live = wait_file(run / "live.json") or {}
    k = kill(live.get("qemu_pid", 0))
    code = p.wait(timeout=60)
    f.close()
    r = rec(run)
    v = verify(run, "N013")
    sh = r.get("shutdown", {})
    obs = {"command": cmd, "operational_seen": op, "killed_qemu_pid": live.get("qemu_pid"), "taskkill_exit": k,
           "exit": code, "result": r.get("result"), "shutdown": sh, "verify": v.get("verdict"), "qemu_left": qemu_pids()}
    ok = op and code == 5 and r.get("result") == "VM_TERMINATED_UNEXPECTEDLY" \
        and sh.get("mode") == "QEMU_EXITED_UNEXPECTEDLY" and v.get("verdict") == "VERIFIED" and not obs["qemu_left"]
    return obs, ok


def e_N014(ctx):
    cmd, p, f = launcher_bg(run_args("N014", stop=90), "N014")
    run = RUNS / (P + "N014")
    live = wait_file(run / "live.json") or {}
    k = kill(live.get("qemu_pid", 0))
    code = p.wait(timeout=60)
    f.close()
    r = rec(run)
    v = verify(run, "N014")
    serial = (run / "serial.log").read_bytes() if (run / "serial.log").is_file() else b""
    obs = {"command": cmd, "killed_qemu_pid": live.get("qemu_pid"), "taskkill_exit": k, "exit": code,
           "result": r.get("result"), "kernel_boot": r.get("verdicts", {}).get("kernel_boot"),
           "detail": r.get("verdicts", {}).get("kernel_boot_detail"),
           "operational_in_serial": b"ABR|STATE|OPERATIONAL" in serial, "verify": v.get("verdict"), "qemu_left": qemu_pids()}
    ok = code == 5 and r.get("result") == "VM_TERMINATED_UNEXPECTEDLY" and not obs["operational_in_serial"] \
        and obs["kernel_boot"] == "FAILED" and v.get("verdict") == "VERIFIED" and not obs["qemu_left"]
    return obs, ok


def e_N015(ctx):
    cmd, p, f = launcher_bg(run_args("N015", stop=90), "N015")
    run = RUNS / (P + "N015")
    op = wait_serial(run)
    time.sleep(5)
    live = wait_file(run / "live.json") or {}
    before = qemu_pids()
    k = kill(p.pid)
    p.wait(timeout=30)
    f.close()
    gone_after = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 5:
        if not qemu_pids():
            gone_after = round(time.monotonic() - t0, 2)
            break
        time.sleep(0.1)
    files = {q.relative_to(run).as_posix(): sha(q) for q in sorted(run.rglob("*")) if q.is_file()}
    (OUT / f"{P}N015.folder-as-left.json").write_text(json.dumps(files, indent=1, sort_keys=True) + "\n")
    ctx["n015_files"] = files
    obs = {"command": cmd, "operational_seen": op, "launcher_pid": p.pid, "qemu_pid": live.get("qemu_pid"),
           "pinned_qemu_before_kill": before, "taskkill_exit": k, "qemu_gone_after_s": gone_after,
           "qemu_left": qemu_pids(), "sealed": "RUN_SHA256SUMS.json" in files, "files_as_left": len(files)}
    ok = op and before == [live.get("qemu_pid")] and gone_after is not None and not obs["qemu_left"] and not obs["sealed"]
    return obs, ok


def e_N016(ctx):
    obs, ok = vm_ok("N016", run_args("N016"))
    r = rec(RUNS / (P + "N016"))
    obs["unsealed_earlier_runs"] = r.get("unsealed_earlier_runs")
    run15 = RUNS / (P + "N015")
    now = {q.relative_to(run15).as_posix(): sha(q) for q in sorted(run15.rglob("*")) if q.is_file()}
    obs["n015_folder_unchanged"] = now == ctx.get("n015_files")
    return obs, ok and obs["unsealed_earlier_runs"] == [P + "N015"] and obs["n015_folder_unchanged"]


def e_N017(ctx):
    a1 = RUNS / (P + "A001")
    before = {q.relative_to(a1).as_posix(): sha(q) for q in sorted(a1.rglob("*")) if q.is_file()}
    cmd = [str(EXE), "--kernel", "production", "--run-id", P + "A001", "--runs-dir", str(RUNS), "--plain", "--no-wait"]
    with open(OUT / f"{P}N017.console.txt", "wb") as f:
        code = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, timeout=60).returncode
    after = {q.relative_to(a1).as_posix(): sha(q) for q in sorted(a1.rglob("*")) if q.is_file()}
    text = (OUT / f"{P}N017.console.txt").read_text(errors="replace")
    obs = {"command": cmd, "exit": code, "a001_unchanged": before == after, "message": text.strip()[-300:],
           "qemu_left": qemu_pids()}
    return obs, code == 7 and before == after and "never reused" in text and not obs["qemu_left"]


def e_X002(ctx):
    rows = []
    for p in sorted(OUT.glob(f"{P}*.verify.json")):
        v = json.loads(p.read_text())
        ag = {k: x for k, x in v.get("checks", {}).items() if k.startswith("agreement_")}
        if ag:
            rows.append({"run": v.get("run_id"), **ag})
    bad = [r for r in rows if not all(x for k, x in r.items() if k != "run")]
    return {"runs_compared": len(rows), "disagreements": bad, "rows": rows}, len(rows) >= 18 and not bad


def e_X003(ctx):
    pairs = [("A001", W / "evidence" / "ABR-BOOT-001" / "ABR-0.33-W001"), ("A004", W / "evidence" / "g033" / "ABR-0.33-L001")]
    obs, ok = {}, True
    for e, ref in pairs:
        run = RUNS / (P + e)
        for f in ("esp/boot/abraham-kernel", "esp/EFI/BOOT/BOOTX64.EFI", "esp/boot/limine/limine.conf"):
            same = (run / f).read_bytes() == (ref / f).read_bytes()
            obs[f"{e} {f} = {ref.name}"] = same
            ok = ok and same
    return obs, ok


def e_V002(ctx):
    n, bad, dec = index_check()
    after = tree_snapshot(W)
    before = ctx["snapshot"]
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    old_after = tree_snapshot(OLD)
    old_changed = sorted(k for k in set(ctx["old_snapshot"]) | set(old_after) if ctx["old_snapshot"].get(k) != old_after.get(k))
    n2, bad2, dec2, zip_ok = old_tree_check()
    old1_after = tree_snapshot(OLD1)
    old1_changed = sorted(k for k in set(ctx["old1_snapshot"]) | set(old1_after) if ctx["old1_snapshot"].get(k) != old1_after.get(k))
    n3, bad3, dec3, zip3 = old1_tree_check()
    obs = {"index_rows": n, "mismatched": bad, "decisions_md": dec, "files_before": len(before), "files_after": len(after),
           "added_removed_or_changed": changed[:50], "vml033_index_rows": n2, "vml033_mismatched": bad2,
           "vml033_decisions_md": dec2, "vml033_package_ok": zip_ok, "vml033_added_removed_or_changed": old_changed[:50],
           "vml0331_index_rows": n3, "vml0331_mismatched": bad3, "vml0331_package_ok": zip3,
           "vml0331_added_removed_or_changed": old1_changed[:50]}
    return obs, (n == 632 and not bad and bool(dec) and dec["append_only"] and not changed and n2 == 559 and not bad2
                 and bool(dec2) and dec2["append_only"] and zip_ok and not old_changed and n3 == 585 and not bad3
                 and bool(dec3) and dec3["append_only"] and zip3 and not old1_changed)


def check_serial(exe, log, kernel):
    r = subprocess.run([str(exe), "--check-serial", str(log), "--kernel", kernel], capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout)


def e_F001(ctx):
    code, d = check_serial(OLD_EXE, STANDBY, "production")
    obs = {"program": sha(OLD_EXE), "exit": code, "boot_checks": d["kernel_boot_checks"], "service_checks": d["service_checks"],
           "first_service_problem": d["service_problems"][:1], "contract": d["launcher_contract"]}
    return obs, d["kernel_boot_checks"].get("heartbeat_continuous") is False \
        and d["service_checks"].get("services_as_designed_every_round") is False


def e_F002(ctx):
    code, d = check_serial(EXE, STANDBY, "production")
    obs = {"program": sha(EXE), "exit": code, "boot_checks": d["kernel_boot_checks"], "service_checks": d["service_checks"],
           "contract": d["launcher_contract"], "gaps": d["clock_gaps_reported_by_the_kernel"], "clock": d["clock_degraded"]}
    return obs, (code == 0 and all(d["kernel_boot_checks"].values()) and all(d["service_checks"].values())
                 and d["launcher_contract"] == "CONSISTENT" and d["clock_gaps_reported_by_the_kernel"] == ["3318 -> 3570, 251 s skipped"]
                 and d["clock_degraded"] == "TSC_FORWARD_JUMP")


def e_F003(ctx):
    logs = [(p, json.loads((p / "launch.json").read_text())["selected_kernel"]["key"]) for p in sorted((OLD / "runs").iterdir())]
    logs += [(OLD / "evidence" / "campaign-vml" / "runs" / f"VML-0.33-{e}", k)
             for e, k in (("A001", "production"), ("A004", "launchpad"), ("A005", "production"), ("A006", "launchpad"))]
    logs += [(W / "evidence" / e, k) for e, k in (
        ("ABR-BOOT-001/ABR-0.33-W001", "production"), ("ABR-BOOT-001/ABR-0.33-W002", "production"),
        ("ABR-BOOT-001/ABR-0.33-T001", "production"), ("ABR-BOOT-001/ABR-0.33-T002", "production"),
        ("g033/ABR-0.33-L001", "launchpad"), ("g033/ABR-0.33-L002", "launchpad"))]
    rows = []
    for p, k in logs:
        code, d = check_serial(EXE, p / "serial.log", k)
        good = code == 0 and all(d["kernel_boot_checks"].values()) and all(d["service_checks"].values()) and \
            d["launcher_contract"] == ("NOT REACHED" if k == "early-fail" else "CONSISTENT")
        rows.append({"log": str(p.relative_to(HOME)), "kernel": k, "exit": code, "contract": d["launcher_contract"],
                     "gaps": d["clock_gaps_reported_by_the_kernel"], "as_expected": good})
    (OUT / f"{P}F003.logs.json").write_text(json.dumps(rows, indent=1) + "\n")
    return {"logs": len(rows), "wrong": [r["log"] for r in rows if not r["as_expected"]]}, len(rows) == 16 and all(r["as_expected"] for r in rows)


def freeze(run, seconds, after_round=None, after_op=10.0):
    if after_round:
        end = time.monotonic() + 120
        while time.monotonic() < end:
            s = run / "serial.log"
            if s.is_file() and s.read_bytes().count(b"ABR|SVCSTATUS|id=svc.netmon") >= after_round:
                break
            time.sleep(0.05)
    else:
        wait_serial(run)
        time.sleep(after_op)
    qpid = (wait_file(run / "live.json") or {}).get("qemu_pid", 0)
    r = subprocess.run([PY, "-I", "-B", str(VML / "tools" / "pause_qemu.py"), str(qpid), str(seconds)],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"error": r.stdout + r.stderr}


def pause_run(entry, kernel, accel, seconds, stop, after_round=None):
    cmd, p, f = launcher_bg(run_args(entry, kernel=kernel, accel=accel, stop=stop), entry)
    run = RUNS / (P + entry)
    fr = freeze(run, seconds, after_round)
    (OUT / f"{P}{entry}.pause.json").write_text(json.dumps(fr, indent=1) + "\n")
    code = p.wait(timeout=300)
    f.close()
    r = rec(run)
    v = verify(run, entry)
    o = r.get("observation", {})
    obs = {"command": cmd, "freeze": fr, "exit": code, "result": r.get("result"), "verdicts": r.get("verdicts"),
           "gaps": o.get("clock_gaps_reported_by_the_kernel"), "stalls": o.get("launcher_stalls"), "clock": o.get("clock_degraded"),
           "clock_anomalies": o.get("clock_anomalies_reported_by_the_kernel"), "service_problems": o.get("service_problems"),
           "verify": v.get("verdict"), "verify_failed": [k for k, x in v.get("checks", {}).items() if not x],
           "verify_checks": {k: x for k, x in v.get("checks", {}).items() if "degraded" in k or k.startswith("agreement")}}
    return obs, code, r, v


def paused_ok(obs, code, r, v, judge="official_launch_probe_degraded_clock"):
    """A freeze of QEMU alone: the gap is reported, its cause is NOT_ESTABLISHED, exit 11, and the judge agrees."""
    gz = obs["gaps"] or []
    vd = obs["verdicts"] or {}
    return (code == 11 and obs["result"] == "CLOCK_ANOMALY_CAUSE_NOT_ESTABLISHED" and len(gz) == 1
            and 25 <= gz[0]["skipped_s"] <= 35 and gz[0]["cause"] == "NOT_ESTABLISHED"
            and obs["clock"] == "TSC_FORWARD_JUMP" and vd.get("kernel_boot") == "PASS" and vd.get("services") == "AS DESIGNED"
            and vd.get("launcher_contract") == "CONSISTENT" and obs["verify"] == "VERIFIED"
            and v.get("checks", {}).get(judge) is True
            and all(v.get("checks", {}).get(k) is True for k in ("agreement_kernel_boot", "agreement_services", "agreement_launcher_contract")))


def e_P001(ctx):
    obs, code, r, v = pause_run("P001", "production", "whpx", 30, 60)
    return obs, paused_ok(obs, code, r, v)


def e_P002(ctx):
    obs, code, r, v = pause_run("P002", "production", "tcg", 30, 60)
    return obs, paused_ok(obs, code, r, v)


def e_P003(ctx):
    obs, code, r, v = pause_run("P003", "production", "whpx", 4, 30, after_round=3)
    vd = obs["verdicts"] or {}
    probs = obs["service_problems"] or []
    ok = (code == 10 and obs["result"] == "SERVICES_NOT_AS_DESIGNED" and not obs["clock_anomalies"] and obs["clock"] is None
          and vd.get("kernel_boot") == "PASS" and vd.get("services") == "PROBLEMS" and vd.get("launcher_contract") == "CONSISTENT"
          and any("at least 250" in x for x in probs) and obs["verify"] == "VERIFIED"
          and v.get("checks", {}).get("agreement_services") is True)
    return obs, ok


def e_P004(ctx):
    obs, code, r, v = pause_run("P004", "launchpad", "whpx", 30, 60)
    return obs, paused_ok(obs, code, r, v, judge="composite_launchpad_degraded_clock")


def e_P006(ctx):
    cmd, p, f = launcher_bg(run_args("P006", stop=60), "P006")
    run = RUNS / (P + "P006")
    wait_serial(run)
    time.sleep(10)
    qpid = (wait_file(run / "live.json") or {}).get("qemu_pid", 0)
    r0 = subprocess.run([PY, "-I", "-B", str(VML / "tools" / "pause_host.py"), str(p.pid), str(qpid), "30"],
                        capture_output=True, text=True)
    fr = json.loads(r0.stdout) if r0.stdout.strip().startswith("{") else {"error": r0.stdout + r0.stderr}
    (OUT / f"{P}P006.pause.json").write_text(json.dumps(fr, indent=1) + "\n")
    code = p.wait(timeout=300)
    f.close()
    r = rec(run)
    v = verify(run, "P006")
    o = r.get("observation", {})
    gz = o.get("clock_gaps_reported_by_the_kernel") or []
    vd = r.get("verdicts") or {}
    obs = {"command": cmd, "freeze": fr, "exit": code, "result": r.get("result"), "gaps": gz, "stalls": o.get("launcher_stalls"),
           "verdicts": vd, "verify": v.get("verdict"), "verify_failed": [k for k, x in v.get("checks", {}).items() if not x]}
    ok = (code == 0 and r.get("result") == "OK" and len(gz) == 1 and gz[0]["cause"].startswith("HOST_SUSPENSION")
          and 25 <= (gz[0].get("launcher_stopped_s") or 0) <= 40 and vd.get("kernel_boot") == "PASS"
          and vd.get("services") == "AS DESIGNED" and vd.get("launcher_contract") == "CONSISTENT" and v.get("verdict") == "VERIFIED")
    return obs, ok


def e_F004(ctx):
    rows = []
    for run in ("ABR-0.33-O003", "ABR-0.33-O004"):
        log = W / "evidence" / "g031b" / run / "serial.log"
        c1, d1 = check_serial(OLD1_EXE, log, "production")
        c2, d2 = check_serial(EXE, log, "production")
        old_mislabel = bool(d1.get("host_pauses_reported_by_the_kernel")) and d1["service_checks"].get("services_as_designed_every_round") is False
        new_ok = (d2.get("clock_gaps_reported_by_the_kernel") == ["3 -> 3603, 3599 s skipped"] and "host_pauses_reported_by_the_kernel" not in d2
                  and all(d2["kernel_boot_checks"].values()) and all(d2["service_checks"].values()) and d2["launcher_contract"] == "CONSISTENT")
        rows.append({"log": run, "0.33.1": {"exit": c1, "host_pauses": d1.get("host_pauses_reported_by_the_kernel"),
                                            "service_problems": d1["service_problems"][:2]},
                     "0.33.2": {"exit": c2, "clock_gaps": d2.get("clock_gaps_reported_by_the_kernel"), "contract": d2["launcher_contract"]},
                     "reproduced": old_mislabel, "corrected": new_ok})
    return {"rows": rows}, all(r["reproduced"] and r["corrected"] for r in rows)


def e_F005(ctx):
    out = OUT / f"{P}F005"
    src = OLD1 / "evidence" / "campaign-vml" / "runs" / "VML-0.33.1-P004" / "serial.log"
    r = subprocess.run([PY, "-I", "-B", str(VML / "tools" / "judge_launchpad_degraded.py"), "selftest", "--source", str(src),
                        "--launchpad", str(W / "evidence" / "g033" / "ABR-0.33-L001" / "serial.log"),
                        "--production-degraded", str(W / "evidence" / "g031b" / "ABR-0.33-O003" / "serial.log"),
                        "--out", str(out)], capture_output=True, text=True)
    (OUT / f"{P}F005.console.txt").write_text(r.stdout + r.stderr)
    rep = json.loads((out / "report.json").read_text()) if (out / "report.json").is_file() else {}
    s = rep.get("summary", {})
    return {"exit": r.returncode, "summary": s, "wrong": [c["case"] for c in rep.get("cases", []) if not c["correct"]]}, \
        r.returncode == 0 and s.get("cases") == s.get("correct") == 9


def e_P005(ctx):
    cmd, p = probe("P005", ["--run-id", P + "P005", "--runs-dir", str(RUNS), "--kernel", "production",
                            "--action", "key-q", "--hold", "15", "--freeze-at", "10", "--freeze-for", "30"])
    v = verify(RUNS / (P + "P005"), "P005")
    obs = {"command": cmd, "probe": p.get("verdict"), "panel_shows_the_pause": p.get("panel_shows_the_pause"),
           "verify": v.get("verdict"), "result": p.get("launch_result")}
    return obs, p.get("verdict") == "PASS" and p.get("panel_shows_the_pause") is True and v.get("verdict") == "VERIFIED"


ORDER = ["V001", "H001", "B001", "S001", "X001", "F001", "F002", "F003", "F004", "F005", "A001", "A002", "A003", "A004",
         "A005", "A006", "A007", "A008", "A009", "A010", "P001", "P002", "P003", "P004", "P005", "P006", "N001", "N002", "N003", "N004", "N005", "N006", "N007", "N008", "N009", "N010", "N011", "N012", "N013",
         "N014", "N015", "N016", "N017", "X002", "X003", "V002"]


def main():
    if OUT.exists():
        raise SystemExit(f"REFUSED: {OUT} exists; campaign ids are never reused")
    assert set(ORDER) == set(EXPECT), "every entry needs a fixed expectation"
    OUT.mkdir(parents=True)
    RUNS.mkdir()
    frozen = source_manifest()
    (OUT / "SOURCE_MANIFEST.json").write_text(json.dumps(frozen, indent=1, sort_keys=True) + "\n")
    (OUT / "EXPECTED.json").write_text(json.dumps(EXPECT, indent=1) + "\n")
    fixtures = Path(tempfile.mkdtemp(prefix="vml-fixtures-"))
    ctx = {"fixtures": fixtures, "fixture_digests": {}}
    record = {"campaign": "ABRAHAM VM LAUNCHER 0.33.2 verification campaign (D-ABR-024, D-ABR-025, D-ABR-026)",
              "started_utc": utc(), "program_sha256": sha(EXE), "python": sys.version.split()[0],
              "qemu_processes_at_start": qemu_pids(pinned_only=False), "fixtures_folder": str(fixtures),
              "entries_defined": len(ORDER), "runs": [], "source_changed_during_campaign": []}
    for e in ORDER:
        t0 = time.monotonic()
        print(f"[{utc()}] {P}{e}: {EXPECT[e]}", flush=True)
        try:
            obs, ok = globals()[f"e_{e}"](ctx)
            err = None
        except Exception as x:  # recorded, never hidden
            obs, ok, err = {}, False, repr(x)
        now = source_manifest()
        if now != frozen:
            record["source_changed_during_campaign"].append(e)
        row = {"id": P + e, "expected": EXPECT[e], "observed": obs, "as_expected": bool(ok) and err is None,
               "error": err, "seconds": round(time.monotonic() - t0, 1), "ended_utc": utc()}
        record["runs"].append(row)
        print(f"    -> {'AS EXPECTED' if row['as_expected'] else 'UNEXPECTED'} ({row['seconds']} s){'  ' + err if err else ''}",
              flush=True)
        (OUT / "campaign.json").write_text(json.dumps(record, indent=1, default=str) + "\n")
    record["fixture_digests"] = ctx["fixture_digests"]
    shutil.rmtree(fixtures, ignore_errors=True)
    record["fixtures_deleted"] = not fixtures.exists()
    record["ended_utc"] = utc()
    record["as_expected"] = sum(1 for r in record["runs"] if r["as_expected"])
    record["unexpected"] = [r["id"] for r in record["runs"] if not r["as_expected"]]
    record["all_as_expected"] = not record["unexpected"] and not record["source_changed_during_campaign"]
    (OUT / "campaign.json").write_text(json.dumps(record, indent=1, default=str) + "\n")
    sums = {p.relative_to(OUT).as_posix(): sha(p) for p in sorted(OUT.rglob("*"))
            if p.is_file() and p.name != "CAMPAIGN_SHA256SUMS.json"}
    (OUT / "CAMPAIGN_SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n")
    print(f"{record['as_expected']}/{len(ORDER)} as expected; unexpected: {record['unexpected']}; "
          f"source changed during campaign: {record['source_changed_during_campaign']}")
    return 0 if record["all_as_expected"] else 1


if __name__ == "__main__":
    sys.exit(main())
