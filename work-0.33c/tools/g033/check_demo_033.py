"""ABRAHAM 0.33: check the hosted launchpad demonstration (D-ABR-022 Q6) against the launcher contract.

  python -I -B tools/g033/check_demo_033.py --out <dir>

Builds and runs `cargo run --offline --example launchpad` (kernel/hosttest/examples/launchpad.rs; label SIMULATED)
three times and holds its output to the same rules as the VM judge (tools/g033/launch_probe.py):
  default        the fixed script: 17 requests in script order, every row exactly as design §9, every result obeying
                 the fact rules, the summary 17/9/6/1/1 with executed=0, the forced RUNNING transition refused;
  own requests   "start app.counterview" "list app" "start app.Browser" "start svc.counter": CAP_MISSING after
                 validation; the registry listed; PARSE_ERROR at STRUCTURE; routed to the 0.32b contract (CAP_MISSING);
  degraded       --degraded-clock: app.counterview UNSATISFIED with svc.counter:UNKNOWN:OBSERVATION_STALE (Q3).
In every run no line claims execution. Outputs are kept and sealed in <dir>. Standard library only.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
W = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "g033"))
import abr_boot_001 as h  # noqa: E402
import launch_probe as lp  # noqa: E402


def run_example(args, out, name):
    env = dict(os.environ, CARGO_TARGET_DIR=str(W / "build" / "demo-target"))
    env.pop("RUSTFLAGS", None)
    r = subprocess.run(["cargo", "run", "--offline", "--example", "launchpad", "--", *args], cwd=W / "kernel" / "hosttest",
                       capture_output=True, text=True, env=env)
    (out / f"{name}.stdout.txt").write_text(r.stdout)
    (out / f"{name}.stderr.txt").write_text(r.stderr)
    return r.returncode, [l.rstrip() for l in r.stdout.splitlines()]


def rows(lines):
    """The requests in order: ("result", fields) | ("query", req) | ("routed", req)."""
    out = []
    for l in lines:
        if l.startswith("ABR|LAUNCHRESULT|"):
            out.append(("result", lp.parse_result(l)))
        elif l.startswith("ABR|APPQUERY|"):
            out.append(("query", l))
        elif l.startswith("ABR|LAUNCH|") and "|routed=SERVICE|" in l:
            out.append(("routed", l))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    out.mkdir(parents=True)
    public = h.appendix_a_codes()
    checks = {}
    rc, ls = run_example([], out, "default")
    got = rows(ls)
    exp = lp.expected_script()
    results = [d for k, d in got if k == "result"]

    def row_ok(e, g):
        req, kind, over = e
        gk, gd = g
        if kind != gk:
            return False
        if kind == "result":
            return gd is not None and gd["req"] == req and all(gd.get(k) == v for k, v in over.items())
        return f"|req={req}|" in gd
    checks["default_exit_0"] = rc == 0
    checks["default_rows_exactly_as_designed"] = len(got) == len(exp) and all(row_ok(e, g) for e, g in zip(exp, got))
    checks["default_results_obey_the_fact_rules"] = bool(results) and all(d and lp.fact_rules_ok(d, public) for d in results)
    checks["default_summary"] = "ABR|LAUNCHPAD|requests=17|refused=9|not_executed=6|discovery=1|routed_to_services=1|executed=0|processes=0|executor=ABSENT" in ls
    checks["default_forced_transition_refused"] = any(l.startswith("forced transition: request 1 (NOT_EXECUTED) -> RUNNING refused with LAUNCH_INVALID_TRANSITION") for l in ls)
    checks["default_routed_answered_cap_missing"] = "ABR|SVCQUERY|op=start|target=svc.counter|result=REFUSED|reason=CAP_MISSING" in ls
    checks["default_no_execution_claimed"] = not h.execution_claims(ls)
    rc, ls2 = run_example(["start app.counterview", "list app", "start app.Browser", "start svc.counter"], out, "own")
    g2 = rows(ls2)
    checks["own_exit_0"] = rc == 0
    checks["own_outcomes"] = (len(g2) == 4 and g2[0][0] == "result" and g2[0][1]["state"] == "NOT_EXECUTED" and g2[0][1]["reason"] == "CAP_MISSING"
                              and g2[1][0] == "query" and "op=list" in g2[1][1]
                              and g2[2][0] == "result" and (g2[2][1]["state"], g2[2][1]["stage"], g2[2][1]["reason"]) == ("REFUSED", "STRUCTURE", "PARSE_ERROR")
                              and g2[3][0] == "routed"
                              and "ABR|SVCQUERY|op=start|target=svc.counter|result=REFUSED|reason=CAP_MISSING" in ls2)
    checks["own_no_execution_claimed"] = not h.execution_claims(ls2)
    rc, ls3 = run_example(["--degraded-clock", "start app.counterview"], out, "degraded")
    cv = [l for l in ls3 if l.startswith("ABR|APPINFO|id=app.counterview|")]
    checks["degraded_exit_0"] = rc == 0
    checks["degraded_counterview_unsatisfied_on_stale_data"] = bool(cv) and all(
        "prerequisites=UNSATISFIED|unavailable=svc.counter:UNKNOWN:OBSERVATION_STALE" in l and l.endswith("clock=DEGRADED") for l in cv)
    checks["degraded_no_execution_claimed"] = not h.execution_claims(ls3)
    rep = {"label": "SIMULATED (the hosted demonstration, checked against the launcher contract)", "checks": checks,
           "example_sha256": h.sha256(W / "kernel" / "hosttest" / "examples" / "launchpad.rs"),
           "verdict": "PASS" if all(checks.values()) else "FAIL"}
    (out / "result.json").write_text(json.dumps(rep, indent=1) + "\n")
    h.seal(out)
    print(json.dumps({"verdict": rep["verdict"], "failed": [k for k, v in checks.items() if not v]}, indent=1))
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
