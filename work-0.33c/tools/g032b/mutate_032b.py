"""ABRAHAM 0.32b mutation check of the hosted service tests (D-ABR-020). Label: SIMULATED.

  python -I -B tools/g032b/mutate_032b.py --out <result dir> [--work <scratch dir, default build/mutants-032b>]

The 0.32 set (tools/g032/mutate_032.py) adapted to the corrected sources: M15 (end-of-cycle dependent stop) no longer
exists and is replaced by M29/M30 (the pre-step guard). M31-M36 target the other 0.32b corrections.

Copies kernel/src and kernel/hosttest (no target) into the scratch tree, checks that the unmutated copy passes every
hosted test, then applies one mutation at a time (each an exact, single-occurrence text replacement in a kernel
source file that the hosted crate compiles unchanged) and runs `cargo test --offline` on the copy. A mutant is KILLED
if the tests fail (or, reported separately, if it does not compile). Every mutant must be killed by a failing test.
The work tree under test is never modified. Results: <out>/mutants.json and per-mutant output, sealed.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

W = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(W / "tools"))
import abr_boot_001 as h  # noqa: E402  (seal only)

MUTANTS = [
    ("M01", "svclife.rs", "an extra transition DECLARED -> RUNNING",
     "            | (SvcState::Starting, SvcState::Running)\n",
     "            | (SvcState::Starting, SvcState::Running)\n            | (SvcState::Declared, SvcState::Running)\n"),
    ("M02", "svclife.rs", "STOPPING -> FAILED no longer allowed", "            | (SvcState::Stopping, SvcState::Failed)\n", ""),
    ("M03", "svcregistry.rs", "topological sort ignores dependencies (no cycle detection)",
     "if !placed[c] && deps_placed(t, c, &placed) && (", "if !placed[c] && ("),
    ("M04", "svcregistry.rs", "ties broken by table position instead of id",
     "(best == usize::MAX || t[c].id.0 < t[best].id.0)", "best == usize::MAX"),
    ("M05", "svcregistry.rs", "name grammar admits upper case", "(c >= b'a' && c <= b'z')", "(c >= b'A' && c <= b'z')"),
    ("M06", "svcregistry.rs", "lookup ignores case", "t.iter().position(|d| bytes_eq(d.name.as_bytes(), name.as_bytes()))",
     "t.iter().position(|d| d.name.eq_ignore_ascii_case(name))"),
    ("M07", "svcregistry.rs", "self-dependency not checked", "if deps[k].0 == t[i].id.0 {", "if false {"),
    ("M08", "svcrun.rs", "start does not wait for dependencies",
     "            if self.state(j) != SvcState::Running {\n                self.rt[idx].withheld_by",
     "            if false {\n                self.rt[idx].withheld_by"),
    ("M09", "svcrun.rs", "readiness without the kernel's independent count", "if units == 0 || observed != Some(units as u64) {",
     "if units == 0 {"),
    ("M10", "svcrun.rs", "the service's own readiness check is skipped", "if let Err(diag) = h.svc_ready(idx) {",
     "if let Err(diag) = Ok::<(), &'static str>(()) {"),
    ("M11", "svcrun.rs", "no work-budget contract check while RUNNING", "            if units > budget {\n",
     "            if units > budget + 1000 {\n"),
    ("M12", "svcrun.rs", "FAILED only after 4 overruns", "pub const FAIL_AFTER_OVERRUNS: u32 = 3;",
     "pub const FAIL_AFTER_OVERRUNS: u32 = 4;"),
    ("M13", "svcrun.rs", "a step exactly at the budget counts as an overrun", "if us > STEP_BUDGET_US {", "if us >= STEP_BUDGET_US {"),
    ("M14", "svcrun.rs", "a backwards TSC reading is measured (wraps) instead of unmeasured",
     "    if after < before || hz == 0 {\n        return None;\n    }\n    let v = ((after - before) as u128)",
     "    if hz == 0 {\n        return None;\n    }\n    let v = ((after.wrapping_sub(before)) as u128)"),
    ("M16", "svcrun.rs", "start does not require OPERATIONAL", "if !h.kernel_operational() {", "if false {"),
    ("M17", "svcrun.rs", "MUTATE operations answered instead of CAP_MISSING",
     "        if class != 0 {\n            return Err(PublicReason::CapMissing);",
     "        if class == 9 {\n            return Err(PublicReason::CapMissing);"),
    ("M18", "svcstatus.rs", "a DEGRADED clock is treated as fresh", "if !matches!(c, ClockTrust::Ok) {",
     "if matches!(c, ClockTrust::Unreadable) {"),
    ("M19", "svcstatus.rs", "freshness interval closed instead of half-open", "n < t.saturating_add(FRESH_MS)",
     "n <= t.saturating_add(FRESH_MS)"),
    ("M20", "svcstatus.rs", "FAILED reports liveness UNKNOWN instead of LOST",
     "SvcState::Failed => ps(3, Status::Unavailable, None, Liveness::Lost, now, c),",
     "SvcState::Failed => ps(3, Status::Unavailable, None, Liveness::Unknown, now, c),"),
    ("M21", "svcstatus.rs", "a not-installed root cause loses its reason",
     "if matches!(i.withheld, DepBlock::NotInstalledRoot) { Some(PublicReason::NotInstalled) } else { None }",
     "if matches!(i.withheld, DepBlock::NotInstalledRoot) { None } else { None }"),
    ("M22", "svcstatus.rs", "loss of liveness sets compromise (P-41 violation)",
     "PublicStatus { status, reason, liveness, compromise: Compromise::NoneKnown, observed_at_ms: at, clock, row }",
     "PublicStatus { status, reason, liveness, compromise: if matches!(liveness, Liveness::Lost) { Compromise::Suspected } "
     "else { Compromise::NoneKnown }, observed_at_ms: at, clock, row }"),
    ("M23", "svc_counter.rs", "the counter wraps instead of failing", "match self.value.checked_add(1) {",
     "match Some(self.value.wrapping_add(1)) {"),
    ("M24", "svcrun.rs", "an external request performs an allowed transition",
     "        h.report(self.table, Report::Refused { idx, r, diag });\n        false\n",
     "        if crate::svclife::allowed(from, to) {\n            return self.go(idx, to, None, h);\n        }\n"
     "        h.report(self.table, Report::Refused { idx, r, diag });\n        false\n"),
    ("M25", "svcrun.rs", "every withheld entry claims a not-installed root cause",
     "            if !self.table[d].installed {\n                return true;",
     "            if true {\n                return true;"),
    ("M26", "svcregistry.rs", "a budget one above the maximum is accepted", "if t[i].budget > MAX_WORK_UNITS {",
     "if t[i].budget > MAX_WORK_UNITS + 1 {"),
    ("M27", "svcregistry.rs", "duplicate dependencies accepted", "if deps[m].0 == deps[k].0 {", "if false {"),
    ("M28", "events.rs", "the SERVICE event kind is misnamed", 'Kind::Service => "SERVICE",', 'Kind::Service => "SVC",'),
    # ---- 0.32b corrections
    ("M29", "svcrun.rs", "finding 1: the pre-step dependency guard is removed",
     "            if !self.deps_running(idx) {\n                self.stop_dependents(h);\n                continue;\n            }\n", ""),
    ("M30", "svcrun.rs", "finding 1: the guard always reports the dependencies RUNNING",
     "self.table[idx].deps.iter().all(|d| matches!(index_of(self.table, *d), Some(j) if self.state(j) == SvcState::Running))",
     "self.table[idx].deps.iter().all(|_| true)"),
    ("M31", "svcrun.rs", "finding 2: an unmeasured step keeps the recovery streak",
     "            r.good = 0; // 0.32b (finding 2): not an in-budget step, so the consecutive streak is broken\n", ""),
    ("M32", "svcrun.rs", "finding 3: the probe's time is not accounted",
     "        if self.account(idx, probe_us, h) {\n            self.fail(idx, \"SVC_STEP_OVERRUN\", h);\n            return;\n        }\n", ""),
    ("M33", "svcrun.rs", "finding 3: an unmeasured probe counts as a fresh success",
     "        if timing != StepTiming::Unmeasured {\n            self.rt[idx].last_step_ms = h.uptime_ms();\n        }",
     "        self.rt[idx].last_step_ms = h.uptime_ms();"),
    ("M34", "svcrun.rs", "finding 3: a probe exactly at the budget is called an overrun",
     "Some(v) if v > STEP_BUDGET_US => StepTiming::Overrun,", "Some(v) if v >= STEP_BUDGET_US => StepTiming::Overrun,"),
    ("M35", "svcrun.rs", "finding 3: readiness always claims an in-budget probe",
     "let timing = StepTiming::of(probe_us);", "let timing = StepTiming::InBudget;"),
    ("M36", "svcrun.rs", "finding 2/3: an unmeasured loop step counts as a fresh success",
     "            if us.is_some() {\n                self.rt[idx].last_step_ms = h.uptime_ms();\n            }",
     "            self.rt[idx].last_step_ms = h.uptime_ms();"),
]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def cargo_test(tree, target):
    env = dict(os.environ, CARGO_TARGET_DIR=str(target))
    env.pop("RUSTFLAGS", None)
    r = subprocess.run(["cargo", "test", "--offline", "--manifest-path", str(tree / "kernel" / "hosttest" / "Cargo.toml")],
                       capture_output=True, text=True, env=env)
    text = r.stdout + "\n--- stderr ---\n" + r.stderr
    counts = [tuple(map(int, m)) for m in re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed", r.stdout)]
    compiled = "could not compile" not in r.stderr and "error[" not in r.stderr
    return r.returncode, text, sum(c[0] for c in counts), sum(c[1] for c in counts), compiled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", default=str(W / "build" / "mutants-032b"))
    a = ap.parse_args()
    out, work = Path(a.out), Path(a.work)
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    out.mkdir(parents=True)
    shutil.rmtree(work, ignore_errors=True)
    tree, target = work / "tree", work / "target"
    shutil.copytree(W / "kernel" / "src", tree / "kernel" / "src")
    shutil.copytree(W / "kernel" / "hosttest", tree / "kernel" / "hosttest", ignore=shutil.ignore_patterns("target"))
    pristine = {p.name: p.read_text(encoding="utf-8") for p in (tree / "kernel" / "src").glob("*.rs")}
    started = datetime.now(timezone.utc).isoformat()
    rc, text, passed, failed, compiled = cargo_test(tree, target)
    (out / "control.out.txt").write_text(text)
    report = {"started_utc": started, "label": "SIMULATED (hosted mutation check)",
              "sources": {f"kernel/src/{n}": sha(W / "kernel" / "src" / n) for n in sorted(pristine)},
              "control": {"exit": rc, "passed": passed, "failed": failed, "ok": rc == 0 and failed == 0 and passed > 0},
              "mutants": []}
    if not report["control"]["ok"]:
        report["verdict"] = "CONTROL_FAILED"
    else:
        for mid, f, what, old, new in MUTANTS:
            src = tree / "kernel" / "src" / f
            n = pristine[f].count(old)
            entry = {"id": mid, "file": f, "mutation": what, "occurrences": n}
            if n != 1:
                entry.update({"applied": False, "killed": False, "note": "mutation text not found exactly once"})
            else:
                src.write_text(pristine[f].replace(old, new), encoding="utf-8")
                rc, text, passed, failed, compiled = cargo_test(tree, target)
                src.write_text(pristine[f], encoding="utf-8")
                (out / f"{mid}.out.txt").write_text(text)
                entry.update({"applied": True, "exit": rc, "compiled": compiled, "tests_passed": passed, "tests_failed": failed,
                              "killed": rc != 0, "killed_by": "test" if (rc != 0 and compiled and failed > 0) else
                              ("compile" if rc != 0 else "SURVIVED")})
            report["mutants"].append(entry)
            print(f"{mid} {entry.get('killed_by', 'NOT APPLIED'):8s} {what}", flush=True)
        ok = all(m["applied"] and m["killed_by"] == "test" for m in report["mutants"])
        report["killed_by_test"] = sum(1 for m in report["mutants"] if m.get("killed_by") == "test")
        report["total"] = len(MUTANTS)
        report["verdict"] = "PASS" if ok else "FAIL"
    report["ended_utc"] = datetime.now(timezone.utc).isoformat()
    (out / "mutants.json").write_text(json.dumps(report, indent=1) + "\n")
    h.seal(out)
    print(json.dumps({k: v for k, v in report.items() if k not in ("mutants", "sources")}, indent=1))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
