"""ABRAHAM 0.33 judge self-test: falsified copies of real runs that the launcher judges must reject (directive Phase 3
item 6: false readiness, false execution, missing refusals, contradictory results, invalid event ordering).

  python -I -B tools/g033/judge_selftest_033.py --production <PASS run, profile 0.33, cold> --launchpad <launch_probe
         PASS run dir> [--refused <launch_probe PASS run dir, app-registry-dup>] --out <dir>

Each case applies ONE falsification to a COPY of a real run (the sources are never modified) and is judged:
  production cases   by the harness (tools/abr_boot_001.py judge, profile 0.33; C8 from the sealed final result);
                     correct only if the verdict is not PASS, C13 is the only failed condition, and every named C13
                     item is false in boot 1;
  launchpad cases    by tools/g033/launch_probe.py (mode launchpad); correct only if the verdict is FAIL and every
                     named check is among the failed ones;
  refused cases      by launch_probe (mode app-registry-dup), the same rule.
Each unmutated control must PASS. Expected answers are fixed here, before any run. Standard library only.
"""
import argparse
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "g033"))
import abr_boot_001 as h  # noqa: E402
import launch_probe as lp  # noqa: E402


def raw(p):
    return Path(p).read_bytes().decode("latin-1").split("\n")


def find(ls, pred, nth=0):
    hits = [i for i, l in enumerate(ls) if pred(l.strip())]
    return hits[nth]


def sub(ls, pred, old, new, nth=0):
    i = find(ls, pred, nth)
    assert old in ls[i], (old, ls[i])
    ls[i] = ls[i].replace(old, new, 1)
    return ls


def starts(prefix):
    return lambda l: l.startswith(prefix)


def has(*parts):
    return lambda l: all(p in l for p in parts)


def insert_after(ls, pred, line, nth=0):
    i = find(ls, pred, nth)
    ls.insert(i + 1, line + "\r")
    return ls


def move_before(ls, src_pred, dst_pred):
    i = find(ls, src_pred)
    line = ls.pop(i)
    j = find(ls, dst_pred)
    ls.insert(j, line)
    return ls


def delete(ls, pred, nth=0):
    ls.pop(find(ls, pred, nth))
    return ls


# ------------------------------------------------------------------ production (C13)
# A production case is correct only if C13 is the only failed condition, except where the falsification necessarily
# breaks another condition too; each such exception is named here, with its reason, before any run.
ALSO_FAILS = {
    # a line inserted before OPERATIONAL also breaks C10's exact lifecycle line sequence (dry-run finding, 2026-11-08)
    "appinfo_before_operational": ["C10_lifecycle_events"],
}
APPINFO_NET = has("ABR|APPINFO|id=app.netstatus|")
APPINFO_CV = has("ABR|APPINFO|id=app.counterview|")
REG = starts("ABR|APP|registry=OK")


def production_cases():
    pre_un = "prerequisites=UNSATISFIED|unavailable=svc.netmon:UNAVAILABLE:NOT_INSTALLED"
    return {
        "control_unmutated": (lambda ls: ls, "PASS", []),
        "appinfo_false_readiness": (lambda ls: sub(ls, APPINFO_NET, pre_un, "prerequisites=SATISFIED|unavailable=NONE"),
                                    "FAIL", ["appinfo_prerequisites_consistent_with_its_round"]),
        "appinfo_false_unavailability": (lambda ls: sub(ls, APPINFO_CV, "prerequisites=SATISFIED|unavailable=NONE",
                                                        "prerequisites=UNSATISFIED|unavailable=svc.counter:UNAVAILABLE:NONE"),
                                         "FAIL", ["appinfo_prerequisites_consistent_with_its_round"]),
        "appinfo_claims_native_execution": (lambda ls: sub(ls, APPINFO_CV, "exec=NONE", "exec=NATIVE"),
                                            "FAIL", ["no_application_executable", "no_execution_claimed"]),
        "registry_claims_an_executor": (lambda ls: sub(ls, REG, "executor=ABSENT", "executor=PRESENT"),
                                        "FAIL", ["application_registry_is_the_production_table", "no_execution_claimed"]),
        "launch_result_in_production": (lambda ls: insert_after(ls, APPINFO_CV,
                                        "ABR|LAUNCHRESULT|req=1|op=start|target=app.counterview|class=MUTATE|admission=FRESH|structure=WELL_FORMED"
                                        "|known=YES|prerequisites=SATISFIED|unavailable=NONE|support=NONE|capability=NONE|authorization=CAP_MISSING"
                                        "|executed=NO|process=NONE|state=NOT_EXECUTED|stage=AUTHORIZATION|result=NOT_EXECUTED"
                                        "|verification=NOT_APPLICABLE|boundary=COOPERATIVE|reason=CAP_MISSING|diag=LAUNCH_CAP_MISSING"),
                                        "FAIL", ["no_launch_request_in_production"]),
        "running_transition_claimed": (lambda ls: insert_after(ls, APPINFO_CV, "ABR|LAUNCH|req=1|seq=1|from=SUBMITTED|to=RUNNING"),
                                       "FAIL", ["no_launch_request_in_production", "no_execution_claimed"]),
        "appinfo_missing_mid_round": (lambda ls: delete(ls, APPINFO_NET, 1), "FAIL", ["appinfo_after_every_status_round"]),
        "appinfo_outside_a_round": (lambda ls: move_before(ls, APPINFO_CV, starts("ABR|SVC|registry=OK")),
                                    "FAIL", ["no_appinfo_outside_a_round"]),
        "registry_before_the_service_start": (lambda ls: move_before(ls, REG, starts("ABR|SVC|registry=OK")),
                                              "FAIL", ["application_registry_once_after_the_service_start"]),
        "registry_printed_twice": (lambda ls: insert_after(ls, REG, ls[find(ls, REG)].strip()),
                                   "FAIL", ["application_registry_once_after_the_service_start"]),
        "registry_wrong_order": (lambda ls: sub(ls, REG, "order=app.counterview,app.netstatus,app.browser",
                                                "order=app.browser,app.counterview,app.netstatus"),
                                 "FAIL", ["application_registry_is_the_production_table"]),
        "appinfo_time_shifted": (lambda ls: shift_time(ls), "FAIL", ["appinfo_time_and_clock_of_its_round"]),
        "appinfo_clock_lies": (lambda ls: sub(ls, APPINFO_CV, "|clock=OK", "|clock=DEGRADED"),
                               "FAIL", ["appinfo_time_and_clock_of_its_round"]),
        "appinfo_unknown_application": (lambda ls: sub(ls, has("ABR|APPINFO|id=app.browser|"), "id=app.browser|", "id=app.browsr|"),
                                        "FAIL", ["appinfo_descriptors_match_the_table"]),
        "appinfo_requirement_changed": (lambda ls: sub(ls, APPINFO_CV, "requires=svc.counter", "requires=NONE"),
                                        "FAIL", ["appinfo_descriptors_match_the_table"]),
        "appinfo_cut_mid_capture": (lambda ls: cut(ls), "FAIL", ["every_application_line_well_formed"]),
        "appinfo_before_operational": (lambda ls: insert_before_operational(ls), "FAIL", ["nothing_before_operational"]),
    }


def shift_time(ls):
    i = find(ls, APPINFO_CV)
    l = ls[i]
    a = l.index("observed_at_ms=") + len("observed_at_ms=")
    b = l.index("|", a)
    ls[i] = l[:a] + str(int(l[a:b]) + 1) + l[b:]
    return ls


def cut(ls):
    i = find(ls, APPINFO_CV)
    ls[i] = ls[i].strip()[:40] + "\r"
    return ls


def insert_before_operational(ls):
    line = ls[find(ls, APPINFO_CV)]
    ls.insert(find(ls, lambda l: l == h.OPERATIONAL), line)
    return ls


def judge_production(case_dir, src_run):
    host0 = json.loads((src_run / "host.json").read_text())
    final0 = json.loads((src_run / "results.json.final").read_text())
    args = argparse.Namespace(run_id=f"case-{case_dir.name}", stable_seconds=15, profile="0.33", expect_memtest=False)
    res = h.judge(case_dir / "serial.log", copy.deepcopy(host0), args)
    res["conditions"]["C8_evidence"] = final0["conditions"]["C8_evidence"]
    res["profile"] = "0.33"
    failed = sorted(c for c, v in res["conditions"].items() if v.get("pass") is False)
    c13 = res["conditions"].get("C13_launcher", {}).get("boot1", {}).get("items", {})
    return h.verdict(res), failed, sorted(k for k, v in c13.items() if not v)


# ------------------------------------------------------------------ launchpad (launch_probe)
def res(req, nth=0):
    return lambda l: l.startswith(f"ABR|LAUNCHRESULT|req={req}|")


def launchpad_cases():
    rule = "every_result_obeys_the_fact_rules"
    return {
        "control_unmutated": (lambda ls: ls, "PASS", []),
        "result_claims_execution": (lambda ls: sub(ls, res(1), "executed=NO", "executed=YES"), "FAIL", ["no_execution_claimed", rule]),
        "result_claims_a_process": (lambda ls: sub(ls, res(1), "process=NONE", "process=7"), "FAIL", ["no_execution_claimed", rule]),
        "result_state_running": (lambda ls: sub(ls, res(1), "state=NOT_EXECUTED", "state=RUNNING"), "FAIL", ["no_execution_claimed", rule]),
        "refusal_missing": (lambda ls: delete(ls, res(8)), "FAIL", ["transitions_right_before_their_result", "the_script_rows_exactly_as_designed"]),
        "refusal_without_its_reason": (lambda ls: sub(ls, res(8), "reason=TARGET_UNKNOWN", "reason=NONE"), "FAIL", [rule]),
        "refused_at_the_authorization_stage": (lambda ls: sub(ls, res(8), "stage=RECOGNITION", "stage=AUTHORIZATION"), "FAIL", [rule]),
        "unknown_target_with_prerequisites": (lambda ls: sub(ls, res(8), "prerequisites=NOT_EVALUATED|unavailable=NOT_EVALUATED",
                                                             "prerequisites=SATISFIED|unavailable=NONE"), "FAIL", [rule]),
        "authz_unavailable_without_a_capability": (lambda ls: sub(sub(ls, res(1), "authorization=CAP_MISSING", "authorization=NO_AUTHORITY"),
                                                                  res(1), "reason=CAP_MISSING|diag=LAUNCH_CAP_MISSING",
                                                                  "reason=AUTHZ_UNAVAILABLE|diag=LAUNCH_NO_AUTHORITY"), "FAIL", [rule]),
        "capability_presented_but_cap_missing": (lambda ls: sub(ls, res(4), "capability=PRESENTED", "capability=NONE"), "FAIL", [rule]),
        "reason_outside_appendix_a": (lambda ls: sub(ls, res(2), "reason=CAP_MISSING", "reason=SERVICE_FAILED"), "FAIL", [rule]),
        "result_false_readiness": (lambda ls: sub(ls, res(2), "prerequisites=UNSATISFIED|unavailable=svc.netmon:UNAVAILABLE:NOT_INSTALLED",
                                                  "prerequisites=SATISFIED|unavailable=NONE"),
                                   "FAIL", ["result_facts_agree_with_the_status_round"]),
        "replay_accepted": (lambda ls: sub(ls, res(1), "admission=NOT_INCREASING", "admission=FRESH", nth=1), "FAIL", [rule]),
        "summary_refused_miscounted": (lambda ls: sub(ls, starts("ABR|LAUNCHPAD|"), "refused=9", "refused=8"),
                                       "FAIL", ["summary_counts_equal_the_lines"]),
        "summary_claims_an_execution": (lambda ls: sub(ls, starts("ABR|LAUNCHPAD|"), "|executed=0|", "|executed=1|"),
                                        "FAIL", ["summary_counts_equal_the_lines", "no_execution_claimed"]),
        "transitions_swapped": (lambda ls: swap(ls, starts("ABR|LAUNCH|req=1|seq=1|"), starts("ABR|LAUNCH|req=1|seq=2|")),
                                "FAIL", ["transitions_right_before_their_result"]),
        "result_before_its_transitions": (lambda ls: move_before(ls, res(2), starts("ABR|LAUNCH|req=2|seq=1|")),
                                          "FAIL", ["transitions_right_before_their_result"]),
        "launch_line_before_operational": (lambda ls: move_before(ls, starts("ABR|LAUNCH|req=1|seq=1|"), lambda l: l == h.OPERATIONAL),
                                           "FAIL", ["nothing_before_operational"]),
        "injection_accepted": (lambda ls: replace_line(ls, starts("ABR|LAUNCH|req=1|refused|"), "ABR|LAUNCH|req=1|seq=3|from=NOT_EXECUTED|to=RUNNING"),
                               "FAIL", ["injection_refused_and_state_unchanged", "no_execution_claimed"]),
        "state_changed_by_the_injection": (lambda ls: sub(ls, starts("ABR|LAUNCH|req=1|state="), "state=NOT_EXECUTED", "state=RUNNING"),
                                           "FAIL", ["injection_refused_and_state_unchanged", "no_execution_claimed"]),
        "routed_request_bypasses_the_contract": (lambda ls: sub(ls, has("ABR|SVCQUERY|op=start|target=svc.counter"),
                                                                "result=REFUSED|reason=CAP_MISSING", "result=OK|status=AVAILABLE|reason=NONE"),
                                                 "FAIL", ["routed_request_answered_by_the_service_contract"]),
        "discovery_answer_false": (lambda ls: sub(ls, lambda l: APPINFO_CV(l) and l == ls[find(ls, starts("ABR|APPQUERY|")) + 1].strip(),
                                                  "prerequisites=SATISFIED|unavailable=NONE",
                                                  "prerequisites=UNSATISFIED|unavailable=svc.counter:UNAVAILABLE:NONE"),
                                   "FAIL", ["discovery_answer_agrees_with_the_status_round"]),
        "malformed_target_echoed": (lambda ls: sub(ls, res(10), "target=MALFORMED|target_len=15", "target=app.CounterView"),
                                    "FAIL", ["the_script_rows_exactly_as_designed"]),
        "requests_out_of_order": (lambda ls: swap_requests(ls, 8, 9), "FAIL", ["request_ids_in_script_order"]),
    }


def swap(ls, a, b):
    i, j = find(ls, a), find(ls, b)
    ls[i], ls[j] = ls[j], ls[i]
    return ls


def replace_line(ls, pred, new):
    ls[find(ls, pred)] = new + "\r"
    return ls


def swap_requests(ls, a, b):
    def block(req):
        i = find(ls, starts(f"ABR|LAUNCH|req={req}|seq=1|"))
        j = find(ls, res(req))
        return i, j
    (ai, aj), (bi, bj) = block(a), block(b)
    assert aj < bi
    blk_a, blk_b = ls[ai:aj + 1], ls[bi:bj + 1]
    return ls[:ai] + blk_b + ls[aj + 1:bi] + blk_a + ls[bj + 1:]


def refused_cases():
    return {
        "control_unmutated": (lambda ls: ls, "PASS", []),
        "appinfo_despite_the_refusal": (lambda ls: insert_after(ls, starts("ABR|APP|registry=REFUSED"),
                                        "ABR|APPINFO|id=app.counterview|kind=VIEWER|rev=1|exec=NONE|requires=svc.counter|prerequisites=SATISFIED"
                                        "|unavailable=NONE|observed_at_ms=83|clock=OK"),
                                        "FAIL", ["no_appinfo_and_no_launch_line"]),
        "refusal_code_changed": (lambda ls: sub(ls, starts("ABR|APP|registry=REFUSED"), "diag=APP_DUPLICATE_ID", "diag=APP_DUPLICATE_NAME"),
                                 "FAIL", ["application_registry_refused_exactly"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--production", required=True)
    ap.add_argument("--launchpad", required=True)
    ap.add_argument("--refused")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    out.mkdir(parents=True)
    report = {"label": "host (judge self-test on copies of real runs)", "sources": {}, "cases": {}}
    prod = Path(a.production)
    report["sources"]["production"] = {"run": str(prod), "serial_sha256": h.sha256(prod / "serial.log")}
    for name, (f, want, items) in production_cases().items():
        d = out / "production" / name
        d.mkdir(parents=True)
        (d / "serial.log").write_bytes("\n".join(f(raw(prod / "serial.log"))).encode("latin-1"))
        shutil.copyfile(prod / "serial-boot2.log", d / "serial-boot2.log")
        got, failed, false_items = judge_production(d, prod)
        must_fail = sorted(["C13_launcher"] + ALSO_FAILS.get(name, []))
        ok = (got == "PASS") if want == "PASS" else (got != "PASS" and failed == must_fail and all(i in false_items for i in items))
        report["cases"][f"production/{name}"] = {"must": want, "judge": got, "failed": failed, "c13_false_items": false_items,
                                                 "intended": items, "correct": ok}
    for kind, src, cases, mode in (("launchpad", a.launchpad, launchpad_cases(), "launchpad"),
                                   ("refused", a.refused, refused_cases(), "app-registry-dup")):
        if not src:
            continue
        serial = Path(src) / "serial.log"
        report["sources"][kind] = {"run": str(src), "serial_sha256": h.sha256(serial)}
        for name, (f, want, items) in cases.items():
            d = out / kind / name
            d.mkdir(parents=True)
            (d / "serial.log").write_bytes("\n".join(f(raw(serial))).encode("latin-1"))
            checks, _ = lp.judge_lines(h.serial_lines(d / "serial.log"), mode)
            failed = sorted(k for k, v in checks.items() if not v)
            got = "PASS" if not failed else "FAIL"
            ok = (got == "PASS") if want == "PASS" else (got == "FAIL" and all(i in failed for i in items))
            report["cases"][f"{kind}/{name}"] = {"must": want, "judge": got, "failed": failed, "intended": items, "correct": ok}
    wrong = sorted(k for k, c in report["cases"].items() if not c["correct"])
    report["summary"] = {"cases": len(report["cases"]), "correct": len(report["cases"]) - len(wrong), "wrong": wrong}
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    h.seal(out)
    for k, c in report["cases"].items():
        print(f"{'ok ' if c['correct'] else 'BAD'} {k:58s} must={c['must']} judge={c['judge']} failed={c['failed'][:4]}")
    print(f"{report['summary']['correct']}/{report['summary']['cases']} {'ALL OK' if not wrong else 'NOT ALL OK'}")
    return 0 if not wrong else 1


if __name__ == "__main__":
    raise SystemExit(main())
