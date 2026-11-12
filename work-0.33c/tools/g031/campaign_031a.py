"""ABRAHAM 0.31a recorded test campaign driver.

  python -I tools/g031/campaign_031a.py freeze          # BUILD_MANIFEST + SOURCE_MANIFEST_START
  python -I tools/g031/campaign_031a.py run [IDS...]    # run all (or the named) entries in order
  python -I tools/g031/campaign_031a.py close           # SOURCE_MANIFEST_END + comparison

Every entry has a fixed command and an EXPECTED outcome written before it runs. The console
output of each run is saved as evidence/campaign-031a/<id>.console.txt and summarised in
campaign.json (command, exit code, expected, as_expected, UTC times, console SHA-256). Kernel
digests come from BUILD_MANIFEST.json (frozen before the first run), never from the file being
tested at run time. Run ids are never reused: an entry whose evidence exists is skipped.
"""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

OS = Path(__file__).resolve().parents[2]
HOME = OS.parent
OUT = OS / "evidence" / "campaign-031a"
QEMU = "C:/Users/XxUnd/abraham-toolchain/qemu/11.1.0-weil-20260811"
EFI = "third_party/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI"
PY = [sys.executable, "-I"]

KERNELS = {
    "default": "build/abraham-kernel-0.31.0-dev.elf",
    "exhaust": "build/diag/abraham-kernel-diag-mem-exhaust.elf",
    "legacy": "build/diag/abraham-kernel-diag-legacy-collision.elf",
    "legacy_guard": "build/diag/abraham-kernel-diag-legacy-collision+diag-memcheck-nonfatal+diag-mem-exhaust.elf",
    "double": "build/diag/abraham-kernel-diag-double-release.elf",
    "ud": "build/diag/abraham-kernel-diag-fault-ud.elf",
    "pf": "build/diag/abraham-kernel-diag-fault-pf.elf",
    "early": "build/diag/abraham-kernel-diag-early-fail.elf",
    "k029": str(HOME / "work-0.29" / "build" / "abraham-kernel-0.1.1.elf"),
}
ACCEPTED_029 = "ef751eafc3bceb7e2f8d9bd1e27a50f91824cb10bff8872856e9485e2f341f4e"
WRONG_DIGEST = "0" * 64


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def manifest():
    return json.loads((OUT / "BUILD_MANIFEST.json").read_text())


def harness(run_id, kernel, accel, profile, restart="cold", extra=(), digest=None):
    d = digest or manifest()["kernels"][kernel]["sha256"]
    return PY + ["tools/abr_boot_001.py", "run", "--run-id", run_id, "--kernel", KERNELS[kernel], "--expect-kernel-sha256", d,
                 "--qemu-dir", QEMU, "--limine-efi", EFI, "--accel", accel, "--profile", profile, "--restart", restart, *extra]


def probe(run_id, kernel, accel, expect):
    return PY + ["tools/g6/fault_probe.py", "--run-id", run_id, "--qemu-dir", QEMU, "--accel", accel,
                 "--cpu", "host" if accel == "whpx" else "max", "--kernel", KERNELS[kernel],
                 "--expect-kernel-sha256", manifest()["kernels"][kernel]["sha256"], "--limine-efi", EFI, "--expect", expect]


# (id, purpose, command builder, expected exit code, evidence path that must not pre-exist)
def entries():
    E = []
    hv = lambda i, *a, **k: (lambda: harness(i, *a, **k))
    pr = lambda i, *a: (lambda: probe(i, *a))
    ev = lambda i: OS / "evidence" / "ABR-BOOT-001" / i
    eg = lambda i: OS / "evidence" / "g6" / i
    # host (SIMULATED)
    E.append(("ABR-0.31a-H001", "host: frame.rs unit, differential, doc and compile-fail tests", lambda: PY + ["tools/g031/host_tests.py", "--run-id", "ABR-0.31a-H001"], 0, OS / "evidence" / "host" / "ABR-0.31a-H001"))
    E.append(("ABR-0.31a-K001", "host: every kernel diagnostic code registered", lambda: PY + ["tools/g031/check_diag_codes.py", "--json", str(OUT / "ABR-0.31a-K001.json")], 0, OUT / "ABR-0.31a-K001.json"))
    E.append(("ABR-0.31a-K002", "host negative: checker fails on an injected unregistered code", lambda: PY + ["tools/g031/check_diag_codes.py", "--root", str(OUT / "K002-tree"), "--json", str(OUT / "ABR-0.31a-K002.json")], 1, OUT / "ABR-0.31a-K002.json"))
    # VM positive (profile 0.31a)
    E.append(("ABR-0.31a-W001", "positive: 0.31a kernel, WHPX, cold restart, C0-C9", hv("ABR-0.31a-W001", "default", "whpx", "0.31a"), 0, ev("ABR-0.31a-W001")))
    E.append(("ABR-0.31a-W002", "positive: 0.31a kernel, WHPX, cold restart, C0-C9", hv("ABR-0.31a-W002", "default", "whpx", "0.31a"), 0, ev("ABR-0.31a-W002")))
    E.append(("ABR-0.31a-T001", "positive: 0.31a kernel, TCG, cold restart, C0-C9", hv("ABR-0.31a-T001", "default", "tcg", "0.31a"), 0, ev("ABR-0.31a-T001")))
    E.append(("ABR-0.31a-T002", "positive: 0.31a kernel, TCG, cold restart, C0-C9", hv("ABR-0.31a-T002", "default", "tcg", "0.31a"), 0, ev("ABR-0.31a-T002")))
    E.append(("ABR-0.31a-R001", "regression: TCG QMP warm reset (D-ABR-007), C0-C9 both boots", hv("ABR-0.31a-R001", "default", "tcg", "0.31a", "warm"), 0, ev("ABR-0.31a-R001")))
    E.append(("ABR-0.31a-R002", "regression: TCG QMP warm reset (D-ABR-007), C0-C9 both boots", hv("ABR-0.31a-R002", "default", "tcg", "0.31a", "warm"), 0, ev("ABR-0.31a-R002")))
    E.append(("ABR-0.31a-E001", "positive+negative: exhaustion on the live kernel, WHPX", hv("ABR-0.31a-E001", "exhaust", "whpx", "0.31a", "cold", ("--expect-memtest",)), 0, ev("ABR-0.31a-E001")))
    E.append(("ABR-0.31a-E002", "positive+negative: exhaustion on the live kernel, TCG", hv("ABR-0.31a-E002", "exhaust", "tcg", "0.31a", "cold", ("--expect-memtest",)), 0, ev("ABR-0.31a-E002")))
    # VM negative controls (expected-fault probes PASS when the expected failure is observed)
    E.append(("ABR-0.31a-N001", "F-029-01 control: 0.29 bump + allocator; live check must stop the boot (WHPX)", pr("ABR-0.31a-N001", "legacy", "whpx", "collision-check"), 0, eg("ABR-0.31a-N001")))
    E.append(("ABR-0.31a-N002", "F-029-01 control: same, TCG", pr("ABR-0.31a-N002", "legacy", "tcg", "collision-check"), 0, eg("ABR-0.31a-N002")))
    E.append(("ABR-0.31a-N003", "D-ABR-012 collision: allocation guard refuses the live table (WHPX)", pr("ABR-0.31a-N003", "legacy_guard", "whpx", "collision-alloc"), 0, eg("ABR-0.31a-N003")))
    E.append(("ABR-0.31a-N004", "D-ABR-012 collision: same, TCG", pr("ABR-0.31a-N004", "legacy_guard", "tcg", "collision-alloc"), 0, eg("ABR-0.31a-N004")))
    E.append(("ABR-0.31a-N005", "D-ABR-012 double release: latched, pool unchanged, stop (WHPX)", pr("ABR-0.31a-N005", "double", "whpx", "double-release"), 0, eg("ABR-0.31a-N005")))
    E.append(("ABR-0.31a-N006", "D-ABR-012 double release: same, TCG", pr("ABR-0.31a-N006", "double", "tcg", "double-release"), 0, eg("ABR-0.31a-N006")))
    E.append(("ABR-0.31a-N007", "C9 not vacuous: the 0.29 kernel judged under profile 0.31a must FAIL", hv("ABR-0.31a-N007", "k029", "whpx", "0.31a"), 1, ev("ABR-0.31a-N007")))
    E.append(("ABR-0.31a-N008", "harness self-test: wrong kernel digest refused, nothing run", hv("ABR-0.31a-N008", "default", "whpx", "0.31a", digest=WRONG_DIGEST), 2, ev("ABR-0.31a-N008")))
    E.append(("ABR-0.31a-N009", "harness self-test: interrupted run (QEMU killed after OPERATIONAL) must FAIL", hv("ABR-0.31a-N009", "default", "whpx", "0.31a", "cold", ("--kill-qemu-after-operational",)), 1, ev("ABR-0.31a-N009")))
    E.append(("ABR-0.31a-N010", "integrity control: tampered 0.31a kernel refused by Limine", hv("ABR-0.31a-N010", "default", "whpx", "0.31a", "cold", ("--negative-hash",)), 0, ev("ABR-0.31a-N010")))
    # regression
    E.append(("ABR-0.31a-G001", "regression: accepted 0.29 kernel under the 0.31a harness, profile 0.29 (WHPX)", hv("ABR-0.31a-G001", "k029", "whpx", "0.29"), 0, ev("ABR-0.31a-G001")))
    E.append(("ABR-0.31a-F001", "regression: #UD reported correctly on 0.31a code (WHPX)", pr("ABR-0.31a-F001", "ud", "whpx", "ud"), 0, eg("ABR-0.31a-F001")))
    E.append(("ABR-0.31a-F002", "regression: #PF reported correctly on 0.31a code (WHPX)", pr("ABR-0.31a-F002", "pf", "whpx", "pf"), 0, eg("ABR-0.31a-F002")))
    E.append(("ABR-0.31a-F003", "regression: #UD, TCG", pr("ABR-0.31a-F003", "ud", "tcg", "ud"), 0, eg("ABR-0.31a-F003")))
    E.append(("ABR-0.31a-F004", "regression: #PF, TCG", pr("ABR-0.31a-F004", "pf", "tcg", "pf"), 0, eg("ABR-0.31a-F004")))
    E.append(("ABR-0.31a-F005", "regression: controlled early-init failure (WHPX)", pr("ABR-0.31a-F005", "early", "whpx", "early"), 0, eg("ABR-0.31a-F005")))
    # harness judge self-test, build reproducibility, series, integrity
    E.append(("ABR-0.31a-J001", "harness self-test: judge falsifications on W001 copies", lambda: PY + ["tools/g031/judge_selftest.py", str(ev("ABR-0.31a-W001")), str(OS / "evidence" / "g031" / "ABR-0.31a-J001")], 0, OS / "evidence" / "g031" / "ABR-0.31a-J001"))
    E.append(("ABR-0.31a-B001", "reproducibility: two clean builds, identical ELF", lambda: PY + ["tools/build.py", "repro"], 0, OUT / "ABR-0.31a-B001.console.txt"))
    E.append(("ABR-0.31a-S001", "C7 series: W001 + W002 + repro", lambda: PY + ["tools/abr_boot_001.py", "series", "ABR-0.31a-W001", "ABR-0.31a-W002"], 0, OUT / "ABR-0.31a-S001.console.txt"))
    E.append(("ABR-0.31a-I002", "integrity: freeze, 0.29 sign-off index and toolchain re-verified at the end", lambda: PY + ["tools/g031/inventory_031.py", str(OUT / "ABR-0.31a-I002.json")], 0, OUT / "ABR-0.31a-I002.json"))
    return E


def tree_manifest():
    files = {}
    for d in ("kernel", "tools", "boot"):
        for p in sorted((OS / d).rglob("*")):
            if p.is_file() and not ({"target", "__pycache__"} & set(p.relative_to(OS).parts)):
                files[p.relative_to(OS).as_posix()] = sha(p)
    return files


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "BUILD_MANIFEST.json").exists():
        raise SystemExit("REFUSED: BUILD_MANIFEST.json exists")
    kernels = {}
    for k, p in KERNELS.items():
        path = OS / p if not Path(p).is_absolute() else Path(p)
        kernels[k] = {"path": p, "sha256": sha(path)}
    if kernels["k029"]["sha256"] != ACCEPTED_029:
        raise SystemExit("REFUSED: the 0.29 kernel is not the accepted ef751eaf")
    infos = {p.relative_to(OS).as_posix(): json.loads(p.read_text()).get("kernel_elf_sha256")
             for p in [OS / "build" / "build-info.json", *sorted((OS / "build" / "diag").glob("build-info-*.json"))]}
    m = {"created_utc": datetime.now(timezone.utc).isoformat(), "kernels": kernels, "build_info_digests": infos}
    (OUT / "BUILD_MANIFEST.json").write_text(json.dumps(m, indent=1) + "\n")
    (OUT / "SOURCE_MANIFEST_START.json").write_text(json.dumps(tree_manifest(), indent=1, sort_keys=True) + "\n")
    print(json.dumps(m, indent=1))


def prepare_k002():
    """A scratch copy of the registry and kernel sources with ONE unregistered code injected."""
    import shutil
    t = OUT / "K002-tree"
    if t.exists():
        return
    shutil.copytree(OS / "kernel" / "src", t / "kernel" / "src")
    shutil.copytree(OS / "kernel" / "asm", t / "kernel" / "asm")
    shutil.copytree(OS / "docs", t / "docs")
    f = t / "kernel" / "src" / "memory.rs"
    f.write_text(f.read_text() + '\n// K002 injected\nconst _K002: &str = "K002_UNREGISTERED_CODE";\n')


def run(selected):
    OUT.mkdir(parents=True, exist_ok=True)
    summary_path = OUT / "campaign.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"runs": []}
    done = {r["id"] for r in summary["runs"]}
    for rid, purpose, build, expected, evidence in entries():
        if selected and rid not in selected:
            continue
        if rid in done or evidence.exists():
            print(f"SKIP {rid}: already run (ids are never reused)")
            continue
        if rid == "ABR-0.31a-K002":
            prepare_k002()
        cmd = build()
        started = datetime.now(timezone.utc).isoformat()
        p = subprocess.run(cmd, cwd=OS, capture_output=True, text=True)
        console = OUT / f"{rid}.console.txt"
        console.write_text(p.stdout + ("\n--- stderr ---\n" + p.stderr if p.stderr else ""))
        rec = {"id": rid, "purpose": purpose, "command": cmd, "expected_exit": expected, "exit": p.returncode,
               "as_expected": p.returncode == expected, "started_utc": started,
               "ended_utc": datetime.now(timezone.utc).isoformat(), "console_sha256": sha(console)}
        summary["runs"].append(rec)
        summary_path.write_text(json.dumps(summary, indent=1) + "\n")
        print(f"{'OK  ' if rec['as_expected'] else 'UNEXPECTED'} {rid} exit={p.returncode} expected={expected}  {purpose}", flush=True)


def close():
    start = json.loads((OUT / "SOURCE_MANIFEST_START.json").read_text())
    end = tree_manifest()
    (OUT / "SOURCE_MANIFEST_END.json").write_text(json.dumps(end, indent=1, sort_keys=True) + "\n")
    changed = sorted(k for k in set(start) | set(end) if start.get(k) != end.get(k))
    summary = json.loads((OUT / "campaign.json").read_text())
    summary["source_changed_during_campaign"] = changed
    summary["all_as_expected"] = all(r["as_expected"] for r in summary["runs"])
    (OUT / "campaign.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({"runs": len(summary["runs"]), "all_as_expected": summary["all_as_expected"],
                      "source_changed_during_campaign": changed}, indent=1))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "freeze":
        freeze()
    elif mode == "run":
        run(set(sys.argv[2:]))
    elif mode == "close":
        close()
    else:
        raise SystemExit(__doc__)
