"""ABRAHAM 0.31a recorded host tests (evidence label SIMULATED: hosted, not the running kernel).

  python -I tools/g031/host_tests.py --run-id ABR-0.31a-H001

1. `cargo test` of kernel/hosttest (the kernel's own frame.rs compiled for the host): unit,
   differential and doc tests. Full output saved.
2. Compile-fail ownership checks, verified for the RIGHT reason: each ```compile_fail,EXXXX block
   in kernel/hosttest/src/lib.rs is compiled with rustc against the test library and must fail
   with exactly that error code (stable rustdoc only checks that compilation fails). The
   compiling twin must compile.
3. Writes evidence/host/<run-id>/ (outputs, result.json) and seals it.
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

OS = Path(__file__).resolve().parents[2]
HOSTTEST = OS / "kernel" / "hosttest"
TARGET = OS / "build" / "hosttest-target"
sys.path.insert(0, str(OS / "tools"))
import abr_boot_001 as h  # noqa: E402  (seal only)

BLOCK = re.compile(r"^//! ```(?P<info>[^\n]*)\n(?P<body>(?://!(?: [^\n]*)?\n)*?)//! ```\n", re.M)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    a = ap.parse_args()
    run = OS / "evidence" / "host" / a.run_id
    if run.exists():
        raise SystemExit(f"REFUSED: {run} exists")
    run.mkdir(parents=True)
    env = dict(os.environ, CARGO_TARGET_DIR=str(TARGET))
    env.pop("RUSTFLAGS", None)
    started = datetime.now(timezone.utc).isoformat()
    inputs = {p.relative_to(OS).as_posix(): sha(p) for p in sorted(HOSTTEST.rglob("*"))
              if p.is_file() and "target" not in p.parts}
    inputs["kernel/src/frame.rs"] = sha(OS / "kernel" / "src" / "frame.rs")

    cmd = ["cargo", "test", "--offline", "--manifest-path", str(HOSTTEST / "Cargo.toml")]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    (run / "cargo-test.out.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr)
    counts = [tuple(map(int, m)) for m in re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", r.stdout)]
    passed, failed = sum(c[0] for c in counts), sum(c[1] for c in counts)

    # 2. compile-fail blocks with their error codes
    lib = (HOSTTEST / "src" / "lib.rs").read_text()
    rlibs = sorted((TARGET / "debug" / "deps").glob("libabraham_frame_hosttest-*.rlib"), key=lambda p: p.stat().st_mtime)
    cf = []
    scratch = run / "compile-fail"
    scratch.mkdir()
    for i, m in enumerate(BLOCK.finditer(lib)):
        info = m["info"].strip()
        body = "\n".join(l[4:] if l.startswith("//! ") else "" for l in m["body"].splitlines())
        src = scratch / f"block{i}.rs"
        src.write_text("#![allow(unused)]\nfn main() {\n" + body + "\n}\n")
        rc = subprocess.run(["rustc", "--edition", "2024", "--crate-type", "bin", str(src),
                             "--extern", f"abraham_frame_hosttest={rlibs[-1]}", "-L", str(TARGET / "debug" / "deps"),
                             "-o", str(scratch / f"block{i}.exe")], capture_output=True, text=True)
        (scratch / f"block{i}.stderr.txt").write_text(rc.stderr)
        codes = sorted(set(re.findall(r"error\[(E\d{4})\]", rc.stderr)))
        if info.startswith("compile_fail"):
            want = info.split(",")[1] if "," in info else None
            ok = rc.returncode != 0 and want is not None and codes == [want]
        else:
            want, ok = None, rc.returncode == 0
        cf.append({"block": i, "info": info, "expected_error": want, "rustc_exit": rc.returncode,
                   "error_codes": codes, "ok": ok})
        (scratch / f"block{i}.exe").unlink(missing_ok=True)
        (scratch / f"block{i}.pdb").unlink(missing_ok=True)

    result = {
        "run_id": a.run_id, "evidence_label": "SIMULATED (hosted unit tests; not the running kernel)",
        "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
        "command": cmd, "cargo_exit": r.returncode, "tests_passed": passed, "tests_failed": failed,
        "result_lines": counts, "compile_fail_checks": cf,
        "rustc": subprocess.run(["rustc", "-V"], capture_output=True, text=True).stdout.strip(),
        "inputs": inputs,
        "verdict": "PASS" if r.returncode == 0 and failed == 0 and passed > 0 and cf and all(c["ok"] for c in cf) else "FAIL",
    }
    (run / "result.json").write_text(json.dumps(result, indent=1) + "\n")
    h.seal(run)
    print(json.dumps({k: v for k, v in result.items() if k not in ("inputs",)}, indent=1))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
