"""ABRAHAM 0.33 mutation check of the hosted launcher tests (D-ABR-022; design §11). Label: SIMULATED.

  python -I -B tools/g033/mutate_033.py --out <result dir> [--work <scratch dir, default build/mutants-033>]

The 0.32b runner (tools/g032b/mutate_032b.py), unchanged, with launcher mutants. It copies kernel/src and
kernel/hosttest (no target) into the scratch tree, checks that the unmutated copy passes every hosted test, then
applies one mutation at a time (an exact, single-occurrence text replacement in a kernel source the hosted crate
compiles unchanged) and runs `cargo test --offline` on the copy. Every mutant must be killed by a failing test (not
merely by a compile error). The work tree under test is never modified. Results: <out>/mutants.json, sealed.
Not mutated, because the type system already forbids it: the launcher reaching a mutating ServiceSet method (it
holds only `&ServiceSet`) and constructing ExecutionEvidence (private field; the compile-fail checks of the hosted
tool prove it).
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
    ("LM01", "launch.rs", "admission: an equal request id is accepted (off by one)",
     "Some(last) if id <= last => Admission::NotIncreasing,", "Some(last) if id < last => Admission::NotIncreasing,"),
    ("LM02", "launch.rs", "prerequisites: a DEGRADED service satisfies (Q3: AVAILABLE only)",
     "if st.status == Status::Available {", "if st.status == Status::Available || st.status == Status::Degraded {"),
    ("LM03", "appregistry.rs", "registry: a NATIVE claim without an executor is accepted",
     "if matches!(apps[i].exec, ExecSupport::Native) && matches!(EXECUTOR, Executor::Absent) {", "if false {"),
    ("LM04", "appregistry.rs", "registry: a wildcard character is accepted in an application name",
     "        } else if (c >= b'a' && c <= b'z') || (c >= b'0' && c <= b'9') {\n            seg += 1;",
     "        } else if (c >= b'a' && c <= b'z') || (c >= b'0' && c <= b'9') || c == b'*' {\n            seg += 1;"),
    ("LM05", "launch.rs", "decision: the operation gate is skipped",
     "if !matches!(f.operation, Operation::Defined) {", "if false {"),
    ("LM06", "launchlife.rs", "lifecycle: VALIDATED -> RUNNING becomes an allowed transition",
     "(Submitted, Refused) | (Submitted, Validated) | (Validated, NotExecuted) => Pair::Allowed,",
     "(Submitted, Refused) | (Submitted, Validated) | (Validated, NotExecuted) | (Validated, Running) => Pair::Allowed,"),
    ("LM07", "launch.rs", "authorization: a presented capability is not recorded as NO_AUTHORITY",
     "f.authorization = if p.capability_presented { Authz::NoAuthority } else { Authz::CapMissing };",
     "f.authorization = if p.capability_presented { Authz::NotEvaluated } else { Authz::CapMissing };"),
    ("LM08", "launch.rs", "recognition: an unknown application is treated as known",
     "                                None => Recognition::Unknown,", "                                None => Recognition::Known(0),"),
    ("LM09", "launch.rs", "facts: a known application's prerequisites are claimed satisfied without reading the services",
     "f.prerequisites = self.prerequisites(i, view);", "f.prerequisites = Prereq::Satisfied;"),
    ("LM10", "launchreq.rs", "parser: a parameter token is no longer refused as a parameter",
     "        if tok.contains(&b'=') {", "        if false {"),
    ("LM11", "launchlife.rs", "lifecycle: a terminal NOT_EXECUTED request can move again",
     "(Submitted, Refused) | (Submitted, Validated) | (Validated, NotExecuted) => Pair::Allowed,",
     "(Submitted, Refused) | (Submitted, Validated) | (Validated, NotExecuted) | (NotExecuted, Validated) => Pair::Allowed,"),
    ("LM12", "launch.rs", "result: a launch result claims execution",
     "pub fn executed(&self) -> bool { false }", "pub fn executed(&self) -> bool { true }"),
    ("LM13", "launchreq.rs", "parser: the 64-byte bound is one byte too loose",
     "if text.len() > MAX_REQUEST_BYTES {", "if text.len() > MAX_REQUEST_BYTES + 1 {"),
    ("LM14", "launch.rs", "discovery: the INSPECT_PUBLIC allow list is widened (show app.x becomes discovery)",
     "(OpClass::InspectPublic, _, _) => Operation::Unknown,", "(OpClass::InspectPublic, _, _) => Operation::Defined,"),
    ("LM15", "launch.rs", "admission: a refused request's id is not used up",
     "            _ => {\n                self.last_admitted = Some(id);\n                Admission::Fresh\n            }",
     "            _ => Admission::Fresh,"),
    ("LM16", "launch.rs", "routing: a service target is handed to the launcher instead of the 0.32b contract",
     "                    if p.ns == Namespace::Service {", "                    if false {"),
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
    ap.add_argument("--work", default=str(W / "build" / "mutants-033"))
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
