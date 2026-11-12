"""ABRAHAM 0.32b: run the hosted reproduction tests for audit findings 1-3 and record which ones fail.

  python -I -B tools/g032b/reproduce_032_defects.py --stage before|after --out <dir>

Runs `cargo test --offline --test repro_0_32_findings` on kernel/hosttest (the kernel's own svc*.rs compiled for the
host). Expectations, fixed before any run:
  --stage before  (the unchanged 0.32 sources): r1..r4 all FAIL, each with its own assertion message, so each
                  defect is reproduced on the real code. Exit 0 if exactly that is observed.
  --stage after   (the corrected 0.32b sources): r1..r4 all PASS. Exit 0 if exactly that is observed.
Also records the SHA-256 of every kernel source the hosted crate compiles. Label: SIMULATED. Sealed.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

OS = Path(__file__).resolve().parents[2]
HOSTTEST = OS / "kernel" / "hosttest"
TARGET = OS / "build" / "hosttest-target"
sys.path.insert(0, str(OS / "tools"))
import abr_boot_001 as h  # noqa: E402  (seal only)

TESTS = {
    "r1_dependent_not_stepped_after_its_dependency_failed_in_the_same_cycle": "the dependent ran a step after its dependency had left RUNNING",
    "r2_unmeasured_step_breaks_the_recovery_streak": "recovered although an unmeasured step interrupted the streak",
    "r3_probe_overrun_is_counted_and_never_reported_available": "a 20 ms probe against a 1 ms budget was reported AVAILABLE",
    "r4_unmeasured_probe_is_never_reported_available": "an unmeasured probe was reported AVAILABLE",
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("before", "after"), required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    out.mkdir(parents=True)
    env = dict(os.environ, CARGO_TARGET_DIR=str(TARGET))
    env.pop("RUSTFLAGS", None)
    started = datetime.now(timezone.utc).isoformat()
    cmd = ["cargo", "test", "--offline", "--manifest-path", str(HOSTTEST / "Cargo.toml"), "--test", "repro_0_32_findings",
           "--", "--test-threads=1"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    text = r.stdout + "\n--- stderr ---\n" + r.stderr
    (out / "cargo-test.out.txt").write_text(text)
    results = {}
    for name, msg in TESTS.items():
        m = re.search(rf"^test {name} \.\.\. (ok|FAILED)$", r.stdout, re.M)
        status = m.group(1) if m else "NOT_RUN"
        results[name] = {"result": status, "expected_message_seen": msg in text}
    if a.stage == "before":
        ok = all(v["result"] == "FAILED" and v["expected_message_seen"] for v in results.values())
    else:
        ok = r.returncode == 0 and all(v["result"] == "ok" for v in results.values())
    srcs = sorted(set(re.findall(r'#\[path = "\.\./\.\./src/([a-z_0-9]+\.rs)"\]', (HOSTTEST / "src" / "lib.rs").read_text())))
    report = {"stage": a.stage, "label": "SIMULATED (hosted)", "started_utc": started,
              "ended_utc": datetime.now(timezone.utc).isoformat(), "command": cmd, "cargo_exit": r.returncode,
              "tests": results, "sources": {f"kernel/src/{s}": sha(OS / "kernel" / "src" / s) for s in srcs},
              "test_file_sha256": sha(HOSTTEST / "tests" / "repro_0_32_findings.rs"),
              "verdict": ("DEFECTS REPRODUCED" if ok else "NOT AS EXPECTED") if a.stage == "before"
                         else ("CORRECTED" if ok else "NOT AS EXPECTED")}
    (out / "result.json").write_text(json.dumps(report, indent=1) + "\n")
    h.seal(out)
    print(json.dumps({k: v for k, v in report.items() if k != "sources"}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
