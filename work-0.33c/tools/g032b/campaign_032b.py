"""ABRAHAM 0.32b recorded test campaign driver (D-ABR-020: the four corrections, and the regressions).

  python -I -B tools/g032b/campaign_032b.py freeze          # BUILD_MANIFEST + SOURCE_MANIFEST_START
  python -I -B tools/g032b/campaign_032b.py run [IDS...]    # run all (or the named) entries in order
  python -I -B tools/g032b/campaign_032b.py close           # SOURCE_MANIFEST_END + comparison

Derived from the 0.32 driver (tools/g032/campaign_032.py). Its rules are unchanged; the ones below are 0.32b's.
The defects themselves were reproduced BEFORE the corrections, in runs X001-X004 (evidence/repro/), outside this
campaign; X005-X007 here show the same tests and cases now answered correctly.

The 0.31b driver's rules, unchanged:
- every entry has a fixed command, an EXPECTED exit code and, where the exit code alone would not prove the point, a
  POST-CHECK that reads the entry's own evidence;
- all are written before anything runs, and an entry is "as expected" only if both match;
- console output goes to evidence/campaign-032/<id>.console.txt, the summary to campaign.json;
- kernel digests come from BUILD_MANIFEST.json, frozen before the first run;
- run ids are never reused.
Reference kernels are the accepted binaries, pinned by digest, never rebuilt (TR-0036 finding 2: the digest depends on
the build path): 0.29 ef751eaf, 0.31a b9a8f8f9, 0.31b ca847b03, and the 0.32 kernel 04878ad5 (not accepted; the
previous revision, regressed under the hardened checker).
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
OUT = W / "evidence" / "campaign-032b"
QEMU = "C:/Users/XxUnd/abraham-toolchain/qemu/11.1.0-weil-20260811"
EFI = "third_party/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI"
PY = [sys.executable, "-I", "-B"]
CP_032 = W / "evidence" / "start" / "ABR-0.32b-V001" / "CHECKPOINT_work-0.32.sha256"
CP_031B = HOME / "work-0.32" / "evidence" / "start" / "ABR-0.32-V001" / "CHECKPOINT_work-0.31b.sha256"
CP_031A = HOME / "work-0.31b" / "evidence" / "start" / "ABR-0.31b-V002" / "CHECKPOINT_work-0.31.sha256"
D = "build/diag/abraham-kernel-"
KERNELS = {
    "default": "build/abraham-kernel-0.32.1-dev.elf",
    "exhaust": D + "diag-mem-exhaust.elf", "legacy": D + "diag-legacy-collision.elf",
    "legacy_guard": D + "diag-legacy-collision+diag-memcheck-nonfatal+diag-mem-exhaust.elf",
    "double": D + "diag-double-release.elf", "ud": D + "diag-fault-ud.elf", "pf": D + "diag-fault-pf.elf",
    "early": D + "diag-early-fail.elf", "overlap": D + "diag-map-overlap.elf", "tsc_back": D + "diag-tsc-backward.elf",
    "tsc_jump": D + "diag-tsc-jump.elf", "init_skip": D + "diag-init-skip.elf",
    "svc_cycle": D + "diag-svc-cycle.elf", "svc_refusals": D + "diag-svc-refusals.elf", "svc_defects": D + "diag-svc-defects.elf",
    "svc_slow": D + "diag-svc-slow.elf", "svc_stall": D + "diag-svc-stall.elf", "svc_cascade": D + "diag-svc-cascade.elf",
    "k029": str(HOME / "work-0.29" / "build" / "abraham-kernel-0.1.1.elf"),
    "k031a": str(HOME / "work-0.31" / "build" / "abraham-kernel-0.31.0-dev.elf"),
    "k031b": str(HOME / "work-0.31b" / "build" / "abraham-kernel-0.31.1-dev.elf"),
    "k032": str(HOME / "work-0.32" / "build" / "abraham-kernel-0.32.0-dev.elf"),
}
PINNED = {"k029": "ef751eafc3bceb7e2f8d9bd1e27a50f91824cb10bff8872856e9485e2f341f4e",
          "k031a": "b9a8f8f9ed8b5f916e280a060a456c9849a510ec6566261639b91b896838aa76",
          "k031b": "ca847b035258bb11258b1867cb9148fed888b2e34e3bf9d1848ad912ea8f1172",
          "k032": "04878ad50645db2c19db42ac9ff7c99298c143a4cbc48badcb15b9c54669c040"}
EV = W / "evidence"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def kpath(k):
    p = Path(KERNELS[k])
    return p if p.is_absolute() else W / p


def digest(k):
    return json.loads((OUT / "BUILD_MANIFEST.json").read_text())["kernels"][k]["sha256"]


def J(p):
    return json.loads(Path(p).read_text())


def lines(p):
    return [l.strip() for l in Path(p).read_bytes().decode("latin-1").replace("\r", "").split("\n")]


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


def c12_items_false(i, boot):
    return sorted(k for k, v in final(i)["conditions"]["C12_services"][boot]["items"].items() if not v)


def service(i, k, accel, expect, seconds=12):
    return lambda: PY + ["tools/g032/service_probe.py", "run", "--run-id", i, "--qemu-dir", QEMU, "--accel", accel,
                         "--kernel", str(kpath(k)), "--expect-kernel-sha256", digest(k), "--limine-efi", EFI, "--expect", expect,
                         "--seconds", str(seconds)]


def final(i):
    return J(EV / "ABR-BOOT-001" / i / "results.json.final")


def failed_conditions(i):
    return {c for c, v in final(i)["conditions"].items() if v.get("pass") is False}


def no_service_line(i):
    return not any(l.startswith("ABR|SVC") for l in lines(EV / "g6" / i / "serial.log"))


def service_context_in_fault(i):
    ls = lines(EV / "g6" / i / "serial.log")
    reg = next((k for k, l in enumerate(ls) if l.startswith("ABR|SVC|registry=OK|")), None)
    flt = next((k for k, l in enumerate(ls) if l.startswith("ABR|FAULT|")), None)
    ctx = [l for l in ls if l.startswith("ABR|FAULTCTX|")]
    return reg is not None and flt is not None and reg < flt and any("|kind=SERVICE|" in l for l in ctx)


def entries():
    E = []
    a = lambda *x: E.append(x)
    ev = lambda d, i: EV / d / i
    P = "ABR-0.32b-"
    W032 = HOME / "work-0.32" / "evidence" / "ABR-BOOT-001" / "ABR-0.32-W001"
    # ---- host (SIMULATED / host checks)
    a(P + "H001", "host: all hosted Rust tests (0.32 set, 4 reproduction tests, 13 correction tests; compile-fail codes with twins)",
      lambda: PY + ["tools/g032/host_tests_032.py", "--run-id", P + "H001"], 0, ev("host", P + "H001"),
      lambda: J(EV / "host" / (P + "H001") / "result.json")["tests_passed"] == 128)
    a(P + "H002", "host: 0.31b tool tests, unchanged",
      lambda: PY + ["-m", "unittest", "discover", "-s", "tools/g031b", "-p", "test_tools_031b.py", "-v"], 0, OUT / (P + "H002.console.txt"), None)
    a(P + "H003", "host: mutation check, 35 mutants (8 for the corrections), each killed by a failing hosted test",
      lambda: PY + ["tools/g032b/mutate_032b.py", "--out", str(EV / "host" / (P + "H003"))], 0, ev("host", P + "H003"),
      lambda: (lambda r: r["killed_by_test"] == r["total"] == 35)(J(EV / "host" / (P + "H003") / "mutants.json")))
    a(P + "X005", "findings 1-3 corrected: the X001 reproduction tests now all PASS on the corrected sources",
      lambda: PY + ["tools/g032b/reproduce_032_defects.py", "--stage", "after", "--out", str(EV / "repro" / (P + "X005"))], 0,
      ev("repro", P + "X005"), lambda: J(EV / "repro" / (P + "X005") / "result.json")["verdict"] == "CORRECTED")
    a(P + "X006", "finding 4 corrected: the X002 falsified cases on the 0.32 W001 run, hardened judge (profile 0.32): all rejected",
      lambda: PY + ["tools/g032b/reproduce_032_c12.py", "--judge", "tools", "--source", str(W032), "--profile", "0.32",
                    "--out", str(EV / "repro" / (P + "X006")), "--require-correct"], 0, ev("repro", P + "X006"),
      lambda: J(EV / "repro" / (P + "X006") / "report.json")["summary"]["judge_correct"] == 11)
    a(P + "Q001", "finding 4: hardening changes no genuine verdict: every sealed 0.32 run re-judged",
      lambda: PY + ["tools/g032b/rejudge_032_runs.py", str(OUT / (P + "Q001.json"))], 0, OUT / (P + "Q001.json"),
      lambda: J(OUT / (P + "Q001.json"))["judged"] == 16)
    a(P + "K001", "host: every printed kernel word registered; public reasons only in svcstatus.rs",
      lambda: PY + ["tools/g032/check_codes_032.py", "--json", str(OUT / (P + "K001.json"))], 0, OUT / (P + "K001.json"), None)
    a(P + "K002", "host negative: checker fails on an injected unregistered code",
      lambda: PY + ["tools/g032/check_codes_032.py", "--root", str(OUT / "K002-tree"), "--json", str(OUT / (P + "K002.json"))],
      1, OUT / (P + "K002.json"), lambda: "K002_UNREGISTERED_CODE" in J(OUT / (P + "K002.json"))["unregistered"])
    a(P + "K003", "host negative: checker fails on an Appendix A code written by hand outside svcstatus.rs",
      lambda: PY + ["tools/g032/check_codes_032.py", "--root", str(OUT / "K003-tree"), "--json", str(OUT / (P + "K003.json"))],
      1, OUT / (P + "K003.json"), lambda: "NOT_INSTALLED" in J(OUT / (P + "K003.json"))["public_reason_written_outside_svcstatus"])
    a(P + "P001", "host (S14): PublicReason = the 27 Appendix A codes in order; no conversion into it",
      lambda: PY + ["tools/g032/check_public_reasons.py", "--json", str(OUT / (P + "P001.json"))], 0, OUT / (P + "P001.json"), None)
    a(P + "P002", "host negative (S14): an injected extra reason SERVICE_FAILED is refused",
      lambda: PY + ["tools/g032/check_public_reasons.py", "--source", str(OUT / "P002-svcstatus.rs"), "--json",
                    str(OUT / (P + "P002.json"))], 1, OUT / (P + "P002.json"), lambda: J(OUT / (P + "P002.json"))["extra"] == ["SERVICE_FAILED"])
    a(P + "S001", "host regression: 0.31b static checks (one owner, no allocator, no dispatch) on the 0.32b ELF",
      lambda: PY + ["tools/g031b/static_checks.py", str(kpath("default")), str(kpath("legacy")), str(OUT / (P + "S001.json"))],
      0, OUT / (P + "S001.json"), None)
    a(P + "S002", "host: 0.32 static checks with the 0.32b names and table",
      lambda: PY + ["tools/g032/static_checks_032.py", str(kpath("default")), str(kpath("svc_defects")), str(OUT / (P + "S002.json"))],
      0, OUT / (P + "S002.json"), None)
    # ---- VM positive, profile 0.32b (C0-C11 + hardened C12)
    for i, acc, rs in (("W001", "whpx", "cold"), ("W002", "whpx", "cold"), ("T001", "tcg", "cold"), ("T002", "tcg", "cold"),
                       ("M001", "tcg", "warm"), ("M002", "tcg", "warm")):
        a(P + i, f"positive: 0.32b kernel, {acc.upper()}, {rs} restart, C0-C12 (hardened)",
          harness(P + i, "default", acc, "0.32b", rs), 0, ev("ABR-BOOT-001", P + i), None)
    for i, acc in (("E001", "whpx"), ("E002", "tcg")):
        a(P + i, f"positive+negative: live exhaustion, {acc.upper()}, C0-C12 with memtest",
          harness(P + i, "exhaust", acc, "0.32b", "cold", ("--expect-memtest",)), 0, ev("ABR-BOOT-001", P + i), None)
    a(P + "X007", "finding 4 on 0.32b evidence: the falsified cases built from W001, profile 0.32b: all rejected",
      lambda: PY + ["tools/g032b/reproduce_032_c12.py", "--judge", "tools", "--source", str(EV / "ABR-BOOT-001" / (P + "W001")),
                    "--profile", "0.32b", "--out", str(EV / "repro" / (P + "X007")), "--require-correct"], 0, ev("repro", P + "X007"),
      lambda: J(EV / "repro" / (P + "X007") / "report.json")["summary"]["judge_correct"] == 11)
    # ---- VM negative: D-ABR-012 repeated on the final 0.32b builds; no service starts in any of them
    for i, k, acc, x in (("N001", "legacy", "whpx", "collision-check"), ("N002", "legacy", "tcg", "collision-check"),
                         ("N003", "legacy_guard", "whpx", "collision-alloc"), ("N004", "legacy_guard", "tcg", "collision-alloc"),
                         ("N005", "double", "whpx", "double-release"), ("N006", "double", "tcg", "double-release"),
                         ("N007", "init_skip", "whpx", "init-skip"), ("N008", "init_skip", "tcg", "init-skip")):
        a(P + i, f"negative: {x}, {acc.upper()} (expected stop observed; no service line)", fault(P + i, k, acc, x), 0,
          ev("g6", P + i), (lambda i=i: no_service_line(P + i)))
    for i, k, acc, x in (("F001", "ud", "whpx", "ud"), ("F002", "ud", "tcg", "ud"), ("F005", "early", "whpx", "early")):
        a(P + i, f"fault report: {x}, {acc.upper()} (before OPERATIONAL: no service line)", fault(P + i, k, acc, x), 0,
          ev("g6", P + i), (lambda i=i: no_service_line(P + i)))
    for i, k, acc, x in (("F003", "pf", "whpx", "pf"), ("F004", "pf", "tcg", "pf")):
        a(P + i, f"fault report: {x}, {acc.upper()} (in OPERATIONAL: SERVICE records in the fault context)",
          fault(P + i, k, acc, x), 0, ev("g6", P + i), (lambda i=i: service_context_in_fault(P + i)))
    # ---- VM clock and map (0.31b checks) and the service part of the clock runs (hardened probe)
    for i, k, acc, x in (("O001", "tsc_back", "whpx", "tsc-backward"), ("O002", "tsc_back", "tcg", "tsc-backward"),
                         ("O003", "tsc_jump", "whpx", "tsc-jump"), ("O004", "tsc_jump", "tcg", "tsc-jump"),
                         ("O005", "overlap", "whpx", "map-overlap"), ("O006", "overlap", "tcg", "map-overlap")):
        a(P + i, f"observation: {x}, {acc.upper()}", observe(P + i, k, acc, x), 0, ev("g031b", P + i), None)
    for i, src, x in (("Y009", "O001", "tsc-backward"), ("Y010", "O002", "tsc-backward"), ("Y011", "O003", "tsc-jump"),
                      ("Y012", "O004", "tsc-jump")):
        a(P + i, f"S16: degraded clock propagates to the service status ({x}, run {src}), hardened probe",
          lambda i=i, src=src, x=x: PY + ["tools/g032/service_probe.py", "judge", "--serial",
                                          str(EV / "g031b" / (P + src) / "serial.log"), "--expect", x,
                                          "--out", str(EV / "g032" / (P + i))], 0, ev("g032", P + i), None)
    # ---- VM service DIAGNOSTIC builds (hardened probe; corrected expectations)
    for i, k, acc, x in (("Y001", "svc_cycle", "whpx", "svc-cycle"), ("Y002", "svc_cycle", "tcg", "svc-cycle"),
                         ("Y003", "svc_refusals", "whpx", "svc-refusals"), ("Y004", "svc_refusals", "tcg", "svc-refusals"),
                         ("Y005", "svc_defects", "whpx", "svc-defects"), ("Y006", "svc_defects", "tcg", "svc-defects"),
                         ("Y007", "svc_slow", "whpx", "svc-slow"), ("Y008", "svc_slow", "tcg", "svc-slow"),
                         ("Y014", "svc_cascade", "whpx", "svc-cascade"), ("Y015", "svc_cascade", "tcg", "svc-cascade")):
        a(P + i, f"service diagnostic: {x}, {acc.upper()}", service(P + i, k, acc, x), 0, ev("g032", P + i), None)
    a(P + "Y013", "service diagnostic (informational): svc-stall, WHPX, 30 s: the misattribution limit",
      service(P + "Y013", "svc_stall", "whpx", "svc-stall", 30), 0, ev("g032", P + "Y013"), None)
    # ---- harness self-tests on real runs
    a(P + "N009", "harness: wrong kernel digest refused, nothing run", harness(P + "N009", "default", "whpx", "0.32b", dig="0" * 64),
      2, ev("ABR-BOOT-001", P + "N009"), lambda: not (EV / "ABR-BOOT-001" / (P + "N009")).exists())
    a(P + "N010", "harness: QEMU killed after OPERATIONAL must FAIL",
      harness(P + "N010", "default", "whpx", "0.32b", "cold", ("--kill-qemu-after-operational",)), 1, ev("ABR-BOOT-001", P + "N010"), None)
    a(P + "N011", "harness: run without the timer opt-out is CONTROL_NOT_QUALIFYING, never PASS",
      harness(P + "N011", "default", "whpx", "0.32b", "cold", ("--no-timer-opt-out",)), 3, ev("ABR-BOOT-001", P + "N011"),
      lambda: final(P + "N011")["verdict"] == "CONTROL_NOT_QUALIFYING")
    a(P + "N012", "integrity: tampered 0.32b kernel refused by Limine",
      harness(P + "N012", "default", "whpx", "0.32b", "cold", ("--negative-hash",)), 0, ev("ABR-BOOT-001", P + "N012"), None)
    # ---- earlier kernels under the hardened harness
    a(P + "G001", "regression: accepted 0.29 kernel, profile 0.29, WHPX", harness(P + "G001", "k029", "whpx", "0.29"), 0,
      ev("ABR-BOOT-001", P + "G001"), None)
    a(P + "G002", "regression: reviewed 0.31a kernel, profile 0.31a, WHPX", harness(P + "G002", "k031a", "whpx", "0.31a"), 0,
      ev("ABR-BOOT-001", P + "G002"), None)
    a(P + "G003", "regression: accepted 0.31b binary (ca847b03), profile 0.31b, WHPX", harness(P + "G003", "k031b", "whpx", "0.31b"), 0,
      ev("ABR-BOOT-001", P + "G003"), None)
    a(P + "G004", "regression: the 0.32b kernel keeps every 0.31b guarantee: profile 0.31b, C0-C11, WHPX",
      harness(P + "G004", "default", "whpx", "0.31b"), 0, ev("ABR-BOOT-001", P + "G004"), None)
    a(P + "G005", "C12 not vacuous: the accepted 0.31b binary under profile 0.32b FAILs on exactly C12",
      harness(P + "G005", "k031b", "whpx", "0.32b"), 1, ev("ABR-BOOT-001", P + "G005"),
      lambda: failed_conditions(P + "G005") == {"C12_services"})
    a(P + "G006", "regression: the 0.32 binary (04878ad5) under its own profile 0.32, judged by the hardened C12: PASS",
      harness(P + "G006", "k032", "whpx", "0.32"), 0, ev("ABR-BOOT-001", P + "G006"), None)
    a(P + "G007", "the 0.32 binary under profile 0.32b FAILs on exactly C12, only for the missing probe_timing claim",
      harness(P + "G007", "k032", "whpx", "0.32b"), 1, ev("ABR-BOOT-001", P + "G007"),
      lambda: failed_conditions(P + "G007") == {"C12_services"}
      and c12_items_false(P + "G007", "boot1") == c12_items_false(P + "G007", "boot2") == ["probe_duration_measured_and_in_budget"])
    # ---- judge self-tests
    a(P + "J001", "harness: hardened C12 falsifications (58 cases) on W001 copies, each failing for its intended reason",
      lambda: PY + ["tools/g032b/judge_selftest_032b.py", str(EV / "ABR-BOOT-001" / (P + "W001")), str(EV / "g032" / (P + "J001"))],
      0, ev("g032", P + "J001"), lambda: J(EV / "g032" / (P + "J001") / "report.json")["cases_total"] == 58)
    a(P + "J002", "harness: the 0.31b C10/C11 falsifications on G004 copies (0.32b kernel, profile 0.31b)",
      lambda: PY + ["tools/g031b/judge_selftest_031b.py", str(EV / "ABR-BOOT-001" / (P + "G004")), str(EV / "g032" / (P + "J002"))],
      0, ev("g032", P + "J002"), None)
    a(P + "J003", "harness: all 0.31a falsifications on W001 copies, profile 0.32b",
      lambda: PY + ["tools/g031/judge_selftest.py", str(EV / "ABR-BOOT-001" / (P + "W001")), str(EV / "g032" / (P + "J003")),
                    "--profile", "0.32b"], 0, ev("g032", P + "J003"), None)
    a(P + "J004", "harness: Echo-finding cases (0.31a audit) on W001 copies, profile 0.32b: all correct",
      lambda: PY + ["tools/g031b/reproduce_031a_findings.py", "--judge", "tools", "--source", str(EV / "ABR-BOOT-001" / (P + "W001")),
                    "--out", str(EV / "g032" / (P + "J004")), "--profile", "0.32b", "--require-correct"], 0, ev("g032", P + "J004"), None)
    # ---- reproducibility and integrity
    a(P + "B001", "reproducibility: two clean builds, identical ELF = tested kernel",
      lambda: PY + ["tools/build.py", "repro"], 0, OUT / (P + "B001.console.txt"),
      lambda: J(W / "build" / "build-info.json")["elf_sha256"] == [digest("default")] * 2)
    a(P + "S003", "C7 series: W001 + W002 + repro",
      lambda: PY + ["tools/abr_boot_001.py", "series", P + "W001", P + "W002"], 0, OUT / (P + "S003.console.txt"), None)
    a(P + "I001", "integrity: freeze, 0.29 sign-off, toolchain re-verified",
      lambda: PY + [str(HOME / "work-0.31" / "tools" / "g031" / "inventory_031.py"), str(OUT / (P + "I001.json"))], 0,
      OUT / (P + "I001.json"), None)
    a(P + "V001", "integrity: the 0.32 tree and its evidence are unchanged since Step 1 (3,445 files)",
      lambda: PY + ["tools/g032/verify_tree_checkpoint.py", "work-0.32", str(CP_032), str(OUT / (P + "V001.json"))], 0,
      OUT / (P + "V001.json"), None)
    a(P + "V002", "integrity: the accepted 0.31b tree is unchanged (2,522 files)",
      lambda: PY + ["tools/g032/verify_tree_checkpoint.py", "work-0.31b", str(CP_031B), str(OUT / (P + "V002.json"))], 0,
      OUT / (P + "V002.json"), None)
    a(P + "V003", "integrity: the reviewed 0.31a tree is unchanged (991 files)",
      lambda: PY + ["tools/g032/verify_tree_checkpoint.py", "work-0.31", str(CP_031A), str(OUT / (P + "V003.json"))], 0,
      OUT / (P + "V003.json"), None)
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
    src_now = {f"kernel/src/{p.name}": sha(p) for p in (W / "kernel" / "src").glob("*.rs")}
    for k, v in kernels.items():
        if k not in PINNED:
            info = W / "build" / "build-info.json" if k == "default" else W / "build" / "diag" / ("build-info-" + Path(v["path"]).stem[len("abraham-kernel-"):] + ".json")
            bi = J(info)
            if bi.get("kernel_elf_sha256") != v["sha256"]:
                raise SystemExit(f"REFUSED: {k} does not match its build-info ({info.name})")
            stale = sorted(n for n, d in bi.get("inputs", {}).items() if n in src_now and src_now[n] != d)
            if stale:
                raise SystemExit(f"REFUSED: {k} was built from older sources: {stale}")
    m = {"created_utc": datetime.now(timezone.utc).isoformat(), "kernels": kernels, "build_info_digests": infos}
    (OUT / "BUILD_MANIFEST.json").write_text(json.dumps(m, indent=1) + "\n")
    (OUT / "SOURCE_MANIFEST_START.json").write_text(json.dumps(tree_manifest(), indent=1, sort_keys=True) + "\n")
    print(json.dumps(m, indent=1))


def prepare(rid):
    for name, rel, line in (("K002", "kernel/src/memory.rs", '\n// K002 injected\nconst _K002: &str = "K002_UNREGISTERED_CODE";\n'),
                            ("K003", "kernel/src/svcmgr.rs", '\n// K003 injected: a public reason written by hand on a diagnostic path\n'
                                                             'const _K003: &str = "NOT_INSTALLED";\n')):
        t = OUT / f"{name}-tree"
        if rid.endswith(name) and not t.exists():
            shutil.copytree(W / "kernel" / "src", t / "kernel" / "src")
            shutil.copytree(W / "kernel" / "asm", t / "kernel" / "asm")
            shutil.copytree(W / "docs", t / "docs")
            f = t / rel
            f.write_text(f.read_text(encoding="utf-8") + line, encoding="utf-8")
    if rid.endswith("P002") and not (OUT / "P002-svcstatus.rs").exists():
        s = (W / "kernel" / "src" / "svcstatus.rs").read_text(encoding="utf-8")
        s = s.replace("    LivenessStale,\n}", "    LivenessStale,\n    ServiceFailed,\n}", 1)
        s = s.replace('PublicReason::LivenessStale => "LIVENESS_STALE",',
                      'PublicReason::LivenessStale => "LIVENESS_STALE",\n            PublicReason::ServiceFailed => "SERVICE_FAILED",', 1)
        (OUT / "P002-svcstatus.rs").write_text(s, encoding="utf-8")


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
        prepare(rid)
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
    s["entries_defined"] = len(entries())
    (OUT / "campaign.json").write_text(json.dumps(s, indent=1) + "\n")
    print(json.dumps({"runs": len(s["runs"]), "entries_defined": s["entries_defined"], "all_as_expected": s["all_as_expected"],
                      "unexpected": [r["id"] for r in s["runs"] if not r["as_expected"]],
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
