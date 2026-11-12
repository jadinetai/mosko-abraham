"""ABRAHAM 0.31b recorded test campaign driver.

  python -I -B tools/g031b/campaign_031b.py freeze          # BUILD_MANIFEST + SOURCE_MANIFEST_START
  python -I -B tools/g031b/campaign_031b.py run [IDS...]    # run all (or the named) entries in order
  python -I -B tools/g031b/campaign_031b.py close           # SOURCE_MANIFEST_END + comparison

Every entry has a fixed command, an EXPECTED exit code and, where the exit code alone would not prove the
point, a POST-CHECK that reads the entry's own evidence. All are written before anything runs. An entry is
"as expected" only if both match. Console output: evidence/campaign-031b/<id>.console.txt; summary:
campaign.json. Kernel digests come from BUILD_MANIFEST.json (frozen before the first run). Run ids are
never reused. Python runs with -B so no bytecode is written into work-0.31 when its judge is imported.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

W = Path(__file__).resolve().parents[2]
HOME = W.parent
OUT = W / "evidence" / "campaign-031b"
QEMU = "C:/Users/XxUnd/abraham-toolchain/qemu/11.1.0-weil-20260811"
EFI = "third_party/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI"
PY = [sys.executable, "-I", "-B"]
CHECKPOINT = W / "evidence" / "start" / "ABR-0.31b-V002" / "CHECKPOINT_work-0.31.sha256"
D = "build/diag/abraham-kernel-"
KERNELS = {
    "default": "build/abraham-kernel-0.31.1-dev.elf",
    "exhaust": D + "diag-mem-exhaust.elf", "legacy": D + "diag-legacy-collision.elf",
    "legacy_guard": D + "diag-legacy-collision+diag-memcheck-nonfatal+diag-mem-exhaust.elf",
    "double": D + "diag-double-release.elf", "ud": D + "diag-fault-ud.elf", "pf": D + "diag-fault-pf.elf",
    "early": D + "diag-early-fail.elf", "overlap": D + "diag-map-overlap.elf", "tsc_back": D + "diag-tsc-backward.elf",
    "tsc_jump": D + "diag-tsc-jump.elf", "init_skip": D + "diag-init-skip.elf",
    "k029": str(HOME / "work-0.29" / "build" / "abraham-kernel-0.1.1.elf"),
    "k031a": str(HOME / "work-0.31" / "build" / "abraham-kernel-0.31.0-dev.elf"),
}
PINNED = {"k029": "ef751eafc3bceb7e2f8d9bd1e27a50f91824cb10bff8872856e9485e2f341f4e",
          "k031a": "b9a8f8f9ed8b5f916e280a060a456c9849a510ec6566261639b91b896838aa76"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def kpath(k):
    p = Path(KERNELS[k])
    return p if p.is_absolute() else W / p


def digest(k):
    return json.loads((OUT / "BUILD_MANIFEST.json").read_text())["kernels"][k]["sha256"]


def J(p):
    return json.loads(Path(p).read_text())


EV = W / "evidence"


def harness(i, k, accel, profile, restart="cold", extra=(), dig=None):
    return lambda: PY + ["tools/abr_boot_001.py", "run", "--run-id", i, "--kernel", str(kpath(k)), "--expect-kernel-sha256",
                         dig or digest(k), "--qemu-dir", QEMU, "--limine-efi", EFI, "--accel", accel, "--profile", profile,
                         "--restart", restart, *extra]


def fault(i, k, accel, expect):
    return lambda: PY + ["tools/g6/fault_probe.py", "--run-id", i, "--qemu-dir", QEMU, "--accel", accel,
                         "--cpu", "host" if accel == "whpx" else "max", "--kernel", str(kpath(k)),
                         "--expect-kernel-sha256", digest(k), "--limine-efi", EFI, "--expect", expect]


def observe(i, k, accel, expect):
    return lambda: PY + ["tools/g031b/observe_probe.py", "--run-id", i, "--qemu-dir", QEMU, "--accel", accel,
                         "--kernel", str(kpath(k)), "--expect-kernel-sha256", digest(k), "--limine-efi", EFI, "--expect", expect]


def final(i):
    return J(EV / "ABR-BOOT-001" / i / "results.json.final")


def failed_conditions(i):
    return {c for c, v in final(i)["conditions"].items() if v.get("pass") is False}


def x001_wrong():
    return set(J(EV / "g031b" / "ABR-0.31b-X001" / "report.json")["summary"]["judge_wrong"])


def window_ok():
    p = J(EV / "g4" / "ABR-0.31b-P001" / "probe.json")["analysis"]
    w = p["window"]
    lines = [json.loads(l) for l in (EV / "g4" / "ABR-0.31b-P001" / "serial-timed.jsonl").read_text().splitlines()]
    inside = [x for x in lines if x["line"].startswith("ABR|TICK|") and w["start_ns"] <= x["t_ns"] <= w["end_ns"]]
    return w["start_ns"] < w["end_ns"] and w["tick_lines"] == len(inside) <= p["tick_lines"] and w["tick_lines"] >= 20


def entries():
    E = []
    a = lambda *x: E.append(x)
    ev = lambda d, i: EV / d / i
    # ---- host (SIMULATED / host checks)
    a("ABR-0.31b-H001", "host: all hosted Rust tests (0.31a + 0.31b, unit, doc, compile-fail codes)",
      lambda: PY + ["tools/g031/host_tests.py", "--run-id", "ABR-0.31b-H001"], 0, ev("host", "ABR-0.31b-H001"), None)
    a("ABR-0.31b-H002", "host: tool tests F-029-02 label, F-029-03 window",
      lambda: PY + ["-m", "unittest", "discover", "-s", "tools/g031b", "-p", "test_tools_031b.py", "-v"], 0, OUT / "ABR-0.31b-H002.console.txt", None)
    a("ABR-0.31b-K001", "host: every kernel diagnostic code registered",
      lambda: PY + ["tools/g031/check_diag_codes.py", "--json", str(OUT / "ABR-0.31b-K001.json")], 0, OUT / "ABR-0.31b-K001.json", None)
    a("ABR-0.31b-K002", "host negative: checker fails on an injected unregistered code",
      lambda: PY + ["tools/g031/check_diag_codes.py", "--root", str(OUT / "K002-tree"), "--json", str(OUT / "ABR-0.31b-K002.json")],
      1, OUT / "ABR-0.31b-K002.json", lambda: "K002_UNREGISTERED_CODE" in J(OUT / "ABR-0.31b-K002.json")["unregistered"])
    a("ABR-0.31b-S001", "host: one owner, no allocator, no dispatch (production ELF + source)",
      lambda: PY + ["tools/g031b/static_checks.py", str(kpath("default")), str(kpath("legacy")), str(OUT / "ABR-0.31b-S001.json")],
      0, OUT / "ABR-0.31b-S001.json", None)
    # ---- Step 3 proof: Echo findings against both judges, and every 0.31a run re-judged
    a("ABR-0.31b-X003", "proof: falsified cases under the UNCHANGED 0.31a judge (defects reproduce)",
      lambda: PY + ["tools/g031b/reproduce_031a_findings.py", "--judge", str(HOME / "work-0.31" / "tools"), "--source",
                    str(HOME / "work-0.31" / "evidence" / "ABR-BOOT-001" / "ABR-0.31a-W001"), "--out", str(EV / "g031b" / "ABR-0.31b-X003"),
                    "--profile", "0.31a"], 0, ev("g031b", "ABR-0.31b-X003"),
      lambda: x001_wrong() <= set(J(EV / "g031b" / "ABR-0.31b-X003" / "report.json")["summary"]["judge_wrong"]))
    a("ABR-0.31b-X004", "proof: same cases under the CORRECTED judge, profile 0.31a: all correct",
      lambda: PY + ["tools/g031b/reproduce_031a_findings.py", "--judge", "tools", "--source",
                    str(HOME / "work-0.31" / "evidence" / "ABR-BOOT-001" / "ABR-0.31a-W001"), "--out", str(EV / "g031b" / "ABR-0.31b-X004"),
                    "--profile", "0.31a", "--require-correct"], 0, ev("g031b", "ABR-0.31b-X004"), None)
    a("ABR-0.31b-Q001", "proof: every sealed 0.31a run re-judged by the corrected judge: verdicts unchanged",
      lambda: PY + ["tools/g031b/rejudge_031a_runs.py", str(OUT / "ABR-0.31b-Q001.json")], 0, OUT / "ABR-0.31b-Q001.json", None)
    # ---- VM positive, profile 0.31b
    for i, acc, rs in (("W001", "whpx", "cold"), ("W002", "whpx", "cold"), ("T001", "tcg", "cold"), ("T002", "tcg", "cold"),
                       ("M001", "tcg", "warm"), ("M002", "tcg", "warm")):
        a(f"ABR-0.31b-{i}", f"positive: 0.31b kernel, {acc.upper()}, {rs} restart, C0-C11",
          harness(f"ABR-0.31b-{i}", "default", acc, "0.31b", rs), 0, ev("ABR-BOOT-001", f"ABR-0.31b-{i}"), None)
    for i, acc in (("E001", "whpx"), ("E002", "tcg")):
        a(f"ABR-0.31b-{i}", f"positive+negative: live exhaustion, {acc.upper()}, C0-C11 with memtest",
          harness(f"ABR-0.31b-{i}", "exhaust", acc, "0.31b", "cold", ("--expect-memtest",)), 0, ev("ABR-BOOT-001", f"ABR-0.31b-{i}"), None)
    # ---- VM negative: D-ABR-012 repeated on the final 0.31b builds
    for i, k, acc, x in (("N001", "legacy", "whpx", "collision-check"), ("N002", "legacy", "tcg", "collision-check"),
                         ("N003", "legacy_guard", "whpx", "collision-alloc"), ("N004", "legacy_guard", "tcg", "collision-alloc"),
                         ("N005", "double", "whpx", "double-release"), ("N006", "double", "tcg", "double-release"),
                         ("N007", "init_skip", "whpx", "init-skip"), ("N008", "init_skip", "tcg", "init-skip")):
        a(f"ABR-0.31b-{i}", f"negative: {x}, {acc.upper()} (expected stop observed)", fault(f"ABR-0.31b-{i}", k, acc, x), 0,
          ev("g6", f"ABR-0.31b-{i}"), None)
    # ---- VM fault reports
    for i, k, acc, x in (("F001", "ud", "whpx", "ud"), ("F002", "ud", "tcg", "ud"), ("F003", "pf", "whpx", "pf"),
                         ("F004", "pf", "tcg", "pf"), ("F005", "early", "whpx", "early")):
        a(f"ABR-0.31b-{i}", f"fault report: {x}, {acc.upper()} (init_state, FAILED, context)", fault(f"ABR-0.31b-{i}", k, acc, x), 0,
          ev("g6", f"ABR-0.31b-{i}"), None)
    # ---- VM clock and map
    for i, k, acc, x in (("O001", "tsc_back", "whpx", "tsc-backward"), ("O002", "tsc_back", "tcg", "tsc-backward"),
                         ("O003", "tsc_jump", "whpx", "tsc-jump"), ("O004", "tsc_jump", "tcg", "tsc-jump"),
                         ("O005", "overlap", "whpx", "map-overlap"), ("O006", "overlap", "tcg", "map-overlap")):
        a(f"ABR-0.31b-{i}", f"observation: {x}, {acc.upper()}", observe(f"ABR-0.31b-{i}", k, acc, x), 0, ev("g031b", f"ABR-0.31b-{i}"), None)
    # ---- harness self-tests on real runs
    a("ABR-0.31b-N009", "harness: wrong kernel digest refused, nothing run", harness("ABR-0.31b-N009", "default", "whpx", "0.31b", dig="0" * 64),
      2, ev("ABR-BOOT-001", "ABR-0.31b-N009"), lambda: not (EV / "ABR-BOOT-001" / "ABR-0.31b-N009").exists())
    a("ABR-0.31b-N010", "harness: QEMU killed after OPERATIONAL must FAIL",
      harness("ABR-0.31b-N010", "default", "whpx", "0.31b", "cold", ("--kill-qemu-after-operational",)), 1, ev("ABR-BOOT-001", "ABR-0.31b-N010"), None)
    a("ABR-0.31b-N011", "harness: run without the timer opt-out is CONTROL_NOT_QUALIFYING, never PASS",
      harness("ABR-0.31b-N011", "default", "whpx", "0.31b", "cold", ("--no-timer-opt-out",)), 3, ev("ABR-BOOT-001", "ABR-0.31b-N011"),
      lambda: final("ABR-0.31b-N011")["verdict"] == "CONTROL_NOT_QUALIFYING")
    a("ABR-0.31b-N012", "integrity: tampered 0.31b kernel refused by Limine",
      harness("ABR-0.31b-N012", "default", "whpx", "0.31b", "cold", ("--negative-hash",)), 0, ev("ABR-BOOT-001", "ABR-0.31b-N012"), None)
    a("ABR-0.31b-J001", "harness: C10/C11 falsifications on W001 copies",
      lambda: PY + ["tools/g031b/judge_selftest_031b.py", str(EV / "ABR-BOOT-001" / "ABR-0.31b-W001"), str(EV / "g031b" / "ABR-0.31b-J001")],
      0, ev("g031b", "ABR-0.31b-J001"), None)
    a("ABR-0.31b-J002", "harness: all 0.31a falsifications on W001 copies, profile 0.31b",
      lambda: PY + ["tools/g031/judge_selftest.py", str(EV / "ABR-BOOT-001" / "ABR-0.31b-W001"), str(EV / "g031b" / "ABR-0.31b-J002"),
                    "--profile", "0.31b"], 0, ev("g031b", "ABR-0.31b-J002"), None)
    a("ABR-0.31b-J003", "harness: Echo-finding cases on W001 copies, profile 0.31b: all correct",
      lambda: PY + ["tools/g031b/reproduce_031a_findings.py", "--judge", "tools", "--source", str(EV / "ABR-BOOT-001" / "ABR-0.31b-W001"),
                    "--out", str(EV / "g031b" / "ABR-0.31b-J003"), "--profile", "0.31b", "--require-correct"], 0, ev("g031b", "ABR-0.31b-J003"), None)
    # ---- regression
    a("ABR-0.31b-G001", "regression: accepted 0.29 kernel, profile 0.29, WHPX", harness("ABR-0.31b-G001", "k029", "whpx", "0.29"), 0,
      ev("ABR-BOOT-001", "ABR-0.31b-G001"), None)
    a("ABR-0.31b-G002", "regression: reviewed 0.31a kernel, profile 0.31a (corrected judge), WHPX", harness("ABR-0.31b-G002", "k031a", "whpx", "0.31a"), 0,
      ev("ABR-BOOT-001", "ABR-0.31b-G002"), None)
    a("ABR-0.31b-G003", "C10/C11 not vacuous: the 0.31a kernel under profile 0.31b FAILs on exactly C10 and C11",
      harness("ABR-0.31b-G003", "k031a", "whpx", "0.31b"), 1, ev("ABR-BOOT-001", "ABR-0.31b-G003"),
      lambda: failed_conditions("ABR-0.31b-G003") == {"C10_lifecycle_events", "C11_clock"})
    a("ABR-0.31b-D001", "F-029-02: diag_reset firmware-only run, TCG: label says firmware only",
      lambda: PY + ["tools/diag_reset.py", "--run-id", "ABR-0.31b-D001", "--accel", "tcg", "--qemu-dir", QEMU], 0, ev("diagnostics", "ABR-0.31b-D001"),
      lambda: J(EV / "diagnostics" / "ABR-0.31b-D001" / "result.json")["label"] == "DIAGNOSTIC (firmware only, no Abraham code)")
    a("ABR-0.31b-D002", "F-029-02: diag_reset with Abraham staged, TCG: label names the kernel, two OPERATIONAL",
      lambda: PY + ["tools/diag_reset.py", "--run-id", "ABR-0.31b-D002", "--accel", "tcg", "--qemu-dir", QEMU, "--abraham", EFI,
                    "--kernel", str(kpath("default")), "--expect-kernel-sha256", digest("default")], 0, ev("diagnostics", "ABR-0.31b-D002"),
      lambda: (lambda r: r["label"] == f"DIAGNOSTIC (Abraham staged: Limine + kernel {digest('default')})"
               and r["abraham_operational_count"] == 2)(J(EV / "diagnostics" / "ABR-0.31b-D002" / "result.json")))
    a("ABR-0.31b-P001", "F-029-03: timing probe, TCG, 30 s: the window is applied and re-verifiable",
      lambda: PY + ["tools/g4/timing_probe.py", "--run-id", "ABR-0.31b-P001", "--qemu-dir", QEMU, "--accel", "tcg", "--cpu", "max",
                    "--kernel", str(kpath("default")), "--limine-efi", EFI, "--seconds", "30", "--no-throttle", "--throttle-mask", "0x4"],
      0, ev("g4", "ABR-0.31b-P001"), window_ok)
    a("ABR-0.31b-B001", "reproducibility: two clean builds, identical ELF = tested kernel",
      lambda: PY + ["tools/build.py", "repro"], 0, OUT / "ABR-0.31b-B001.console.txt",
      lambda: J(W / "build" / "build-info.json")["elf_sha256"] == [digest("default")] * 2)
    a("ABR-0.31b-S002", "C7 series: W001 + W002 + repro",
      lambda: PY + ["tools/abr_boot_001.py", "series", "ABR-0.31b-W001", "ABR-0.31b-W002"], 0, OUT / "ABR-0.31b-S002.console.txt", None)
    a("ABR-0.31b-I002", "integrity: freeze, 0.29 sign-off, toolchain re-verified",
      lambda: PY + [str(HOME / "work-0.31" / "tools" / "g031" / "inventory_031.py"), str(OUT / "ABR-0.31b-I002.json")], 0,
      OUT / "ABR-0.31b-I002.json", None)
    a("ABR-0.31b-V003", "integrity: the reviewed 0.31a tree is unchanged since Step 1 (991 files)",
      lambda: PY + ["tools/g031b/verify_checkpoint.py", str(CHECKPOINT), str(OUT / "ABR-0.31b-V003.json")], 0, OUT / "ABR-0.31b-V003.json", None)
    return E


def tree_manifest():
    files = {}
    for d in ("kernel", "tools", "boot"):
        for p in sorted((W / d).rglob("*")):
            if p.is_file() and not ({"target", "__pycache__"} & set(p.relative_to(W).parts)):
                files[p.relative_to(W).as_posix()] = sha(p)
    return files


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "BUILD_MANIFEST.json").exists():
        raise SystemExit("REFUSED: BUILD_MANIFEST.json exists")
    kernels = {k: {"path": KERNELS[k], "sha256": sha(kpath(k))} for k in KERNELS}
    for k, pinned in PINNED.items():
        if kernels[k]["sha256"] != pinned:
            raise SystemExit(f"REFUSED: reference kernel {k} is not {pinned}")
    infos = {p.relative_to(W).as_posix(): J(p).get("kernel_elf_sha256")
             for p in [W / "build" / "build-info.json", *sorted((W / "build" / "diag").glob("build-info-*.json"))]}
    for k, v in kernels.items():
        if k not in PINNED:
            info = W / "build" / "build-info.json" if k == "default" else W / "build" / "diag" / ("build-info-" + Path(v["path"]).stem[len("abraham-kernel-"):] + ".json")
            if J(info).get("kernel_elf_sha256") != v["sha256"]:
                raise SystemExit(f"REFUSED: {k} does not match its build-info ({info.name})")
    m = {"created_utc": datetime.now(timezone.utc).isoformat(), "kernels": kernels, "build_info_digests": infos}
    (OUT / "BUILD_MANIFEST.json").write_text(json.dumps(m, indent=1) + "\n")
    (OUT / "SOURCE_MANIFEST_START.json").write_text(json.dumps(tree_manifest(), indent=1, sort_keys=True) + "\n")
    print(json.dumps(m, indent=1))


def prepare_k002():
    t = OUT / "K002-tree"
    if t.exists():
        return
    shutil.copytree(W / "kernel" / "src", t / "kernel" / "src")
    shutil.copytree(W / "kernel" / "asm", t / "kernel" / "asm")
    shutil.copytree(W / "docs", t / "docs")
    f = t / "kernel" / "src" / "memory.rs"
    f.write_text(f.read_text() + '\n// K002 injected\nconst _K002: &str = "K002_UNREGISTERED_CODE";\n')


def run(selected):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "campaign.json"
    summary = J(path) if path.exists() else {"runs": []}
    done = {r["id"] for r in summary["runs"]}
    for rid, purpose, build, expected, evidence, post in entries():
        if selected and rid not in selected:
            continue
        if rid in done or evidence.exists():
            print(f"SKIP {rid}: already run (ids are never reused)", flush=True)
            continue
        if rid.endswith("K002"):
            prepare_k002()
        cmd = build()
        started = datetime.now(timezone.utc).isoformat()
        p = subprocess.run(cmd, cwd=W, capture_output=True, text=True)
        console = OUT / f"{rid}.console.txt"
        console.write_text(p.stdout + ("\n--- stderr ---\n" + p.stderr if p.stderr else ""))
        try:
            post_ok = post() if post else None
        except Exception as e:  # noqa: BLE001  a post-check that cannot read its evidence fails
            post_ok = False
            console.write_text(console.read_text() + f"\n--- post-check error ---\n{e!r}\n")
        rec = {"id": rid, "purpose": purpose, "command": [str(c) for c in cmd], "expected_exit": expected, "exit": p.returncode,
               "post_check": None if post is None else bool(post_ok),
               "as_expected": p.returncode == expected and post_ok is not False, "started_utc": started,
               "ended_utc": datetime.now(timezone.utc).isoformat(), "console_sha256": sha(console)}
        summary["runs"].append(rec)
        path.write_text(json.dumps(summary, indent=1) + "\n")
        print(f"{'OK  ' if rec['as_expected'] else 'UNEXPECTED'} {rid} exit={p.returncode} expected={expected}"
              f"{'' if post is None else ' post=' + str(bool(post_ok))}  {purpose}", flush=True)


def close():
    start = J(OUT / "SOURCE_MANIFEST_START.json")
    end = tree_manifest()
    (OUT / "SOURCE_MANIFEST_END.json").write_text(json.dumps(end, indent=1, sort_keys=True) + "\n")
    changed = sorted(k for k in set(start) | set(end) if start.get(k) != end.get(k))
    s = J(OUT / "campaign.json")
    s["source_changed_during_campaign"] = changed
    s["all_as_expected"] = all(r["as_expected"] for r in s["runs"])
    (OUT / "campaign.json").write_text(json.dumps(s, indent=1) + "\n")
    print(json.dumps({"runs": len(s["runs"]), "all_as_expected": s["all_as_expected"], "unexpected":
                      [r["id"] for r in s["runs"] if not r["as_expected"]], "source_changed_during_campaign": changed}, indent=1))


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
