"""ABRAHAM 0.33c / launcher 0.33.2 (D-ABR-026 Phase 3B): a COMPOSITE judge for the DIAGNOSTIC launchpad build on a
DEGRADED clock, built only from the official rule sets of work-0.33/tools/g033/launch_probe.py (imported read-only,
never modified). It changes no application contract and adds no rule of its own beyond selecting and combining them.

  python -I -B tools/judge_launchpad_degraded.py judge --serial <serial.log> [--out <result.json>]
  python -I -B tools/judge_launchpad_degraded.py selftest --source <serial.log of a launchpad run across a pause>
         --launchpad <serial.log of a normal launchpad run> --production-degraded <serial.log of a tsc-jump run>
         --out <folder>

Why it is needed: launch_probe's `launchpad` mode requires svc.counter AVAILABLE in every status round (its rule
`counter_available_and_increasing_every_round`), which a DEGRADED clock forbids by design; its `degraded-clock` mode
requires that no launch line exists, which the launchpad build contradicts by design. Neither official mode can judge
this case, so TR-0046 P004 was NOT VERIFIED.

The composite takes:
  - every check of launch_probe.judge_lines(lines, "launchpad") EXCEPT counter_available_and_increasing_every_round
    (the 0.32b service checks, the 17-row design script, transitions, fact rules, facts against the round, discovery,
    routed request, summary, the refused RUNNING transition, no execution claim, launcher codes registered);
  - from launch_probe.judge_lines(lines, "degraded-clock"): counterview_satisfied_before_the_anomaly and
    counterview_unsatisfied_on_stale_data_after_it (never satisfied on stale data, D-ABR-022 Q3);
  - one applicability check: the kernel itself reported `ABR|CLOCK|state=DEGRADED` (the composite judges nothing else).
Its verdict is labelled COMPOSITE, never OFFICIAL. Standard library only.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parents[2]
W = HOME / "work-0.33"
sys.path.insert(0, str(W / "tools"))
sys.path.insert(0, str(W / "tools" / "g033"))
import abr_boot_001 as h  # noqa: E402
import launch_probe as lp  # noqa: E402

DROPPED = "counter_available_and_increasing_every_round"
DEGRADED_KEYS = ("counterview_satisfied_before_the_anomaly", "counterview_unsatisfied_on_stale_data_after_it")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def judge_lines(lines):
    c_lp, i_lp = lp.judge_lines(lines, "launchpad")
    c_dc, _ = lp.judge_lines(lines, "degraded-clock")
    checks = {"applies_the_kernel_reported_a_degraded_clock": any(l.startswith("ABR|CLOCK|state=DEGRADED|") for l in lines)}
    checks.update({k: v for k, v in c_lp.items() if k != DROPPED})
    checks.update({k: c_dc[k] for k in DEGRADED_KEYS})
    info = {"launchpad_checks_used": len(c_lp) - 1, "degraded_checks_used": list(DEGRADED_KEYS), "dropped": DROPPED,
            "rounds": i_lp.get("rounds")}
    return checks, info


def judge_file(serial):
    checks, info = judge_lines(h.serial_lines(Path(serial)))
    return {"verdict": "PASS" if all(checks.values()) else "FAIL", "kind": "COMPOSITE (launch_probe launchpad + degraded-clock rules)",
            "checks": checks, **info, "serial": str(serial), "serial_sha256": sha(serial),
            "launch_probe_sha256": sha(W / "tools" / "g033" / "launch_probe.py")}


def selftest(a):
    """Positive control, falsifications that must each FAIL for their intended reason, and non-vacuity controls."""
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    base = h.serial_lines(Path(a.source))
    deg = next(i for i, l in enumerate(base) if l.startswith("ABR|CLOCK|state=DEGRADED|"))
    after = lambda pfx: next(i for i in range(deg, len(base)) if base[i].startswith(pfx))

    def edit(fn):
        v = list(base)
        fn(v)
        return v

    def stale_to_available(v):
        i = after("ABR|SVCSTATUS|id=svc.counter")
        v[i] = v[i].replace("status=UNKNOWN|reason=OBSERVATION_STALE|liveness=UNKNOWN", "status=AVAILABLE|reason=NONE|liveness=LIVE")

    def satisfied_on_stale(v):
        i = after("ABR|APPINFO|id=app.counterview")
        v[i] = v[i].replace("prerequisites=UNSATISFIED|unavailable=svc.counter:UNKNOWN:OBSERVATION_STALE", "prerequisites=SATISFIED|unavailable=NONE")

    def execution_claim(v):
        i = next(i for i, l in enumerate(v) if l.startswith("ABR|LAUNCHRESULT|req=1|"))
        v[i] = v[i].replace("|executed=NO|", "|executed=YES|")

    def drop_transition(v):
        i = next(i for i, l in enumerate(v) if l.startswith("ABR|LAUNCH|req=3|seq=2|"))
        del v[i]

    def miscount(v):
        i = next(i for i, l in enumerate(v) if l.startswith("ABR|LAUNCHPAD|"))
        v[i] = v[i].replace("|refused=9|", "|refused=8|")

    def drop_degraded(v):
        del v[deg]

    cases = [
        ("control_unmutated", base, "PASS", []),
        ("stale_counter_claimed_available", edit(stale_to_available), "FAIL",
         ["status_lines_consistent_with_transitions_mapping_and_clock", "appinfo_rounds_consistent"]),
        ("counterview_satisfied_on_stale_data", edit(satisfied_on_stale), "FAIL",
         ["counterview_unsatisfied_on_stale_data_after_it", "appinfo_rounds_consistent"]),
        ("launch_result_claims_execution", edit(execution_claim), "FAIL", ["no_execution_claimed", "every_result_obeys_the_fact_rules"]),
        ("a_transition_missing", edit(drop_transition), "FAIL", ["transitions_right_before_their_result"]),
        ("summary_miscounted", edit(miscount), "FAIL", ["summary_counts_equal_the_lines"]),
        ("no_degraded_report_by_the_kernel", edit(drop_degraded), "FAIL", ["applies_the_kernel_reported_a_degraded_clock"]),
        ("non_vacuity_a_normal_launchpad_run", h.serial_lines(Path(a.launchpad)), "FAIL",
         ["applies_the_kernel_reported_a_degraded_clock"]),
        ("non_vacuity_a_production_run_on_a_degraded_clock", h.serial_lines(Path(a.production_degraded)), "FAIL",
         ["the_script_rows_exactly_as_designed"]),
    ]
    rows = []
    for name, lines, want, intended in cases:
        checks, _ = judge_lines(lines)
        verdict = "PASS" if all(checks.values()) else "FAIL"
        failed = sorted(k for k, v in checks.items() if not v)
        ok = verdict == want and (not intended or any(k in failed for k in intended))
        rows.append({"case": name, "must": want, "verdict": verdict, "failed": failed, "intended": intended, "correct": ok})
        (out / f"{name}.serial.log").write_text("\n".join(lines) + "\n", encoding="latin-1")
    rep = {"composite_judge": str(Path(__file__).resolve()), "composite_judge_sha256": sha(Path(__file__).resolve()),
           "sources": {"source": str(a.source), "source_sha256": sha(a.source), "launchpad": str(a.launchpad),
                       "production_degraded": str(a.production_degraded)},
           "cases": rows, "summary": {"cases": len(rows), "correct": sum(r["correct"] for r in rows)}}
    (out / "report.json").write_text(json.dumps(rep, indent=1) + "\n")
    sums = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out / "RUN_SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n")
    print(json.dumps(rep["summary"]), [r["case"] for r in rows if not r["correct"]])
    return 0 if rep["summary"]["correct"] == len(rows) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    j = sub.add_parser("judge")
    j.add_argument("--serial", required=True)
    j.add_argument("--out")
    s = sub.add_parser("selftest")
    s.add_argument("--source", required=True)
    s.add_argument("--launchpad", required=True)
    s.add_argument("--production-degraded", required=True)
    s.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.mode == "selftest":
        return selftest(a)
    r = judge_file(a.serial)
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=1) + "\n")
    print(json.dumps({"verdict": r["verdict"], "failed": [k for k, v in r["checks"].items() if not v]}))
    return 0 if r["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
