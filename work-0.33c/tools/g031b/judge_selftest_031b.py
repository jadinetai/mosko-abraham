"""ABRAHAM 0.31b judge self-test for the new conditions C10 (lifecycle, event log) and C11 (clock).

  python -I -B tools/g031b/judge_selftest_031b.py <PASS run, profile 0.31b, cold restart> <output dir>

Applies one falsification at a time to COPIES of a real 0.31b PASS run, judges each with the 0.31b judge
under profile 0.31b, and requires a non-PASS verdict for every falsification and PASS for the unchanged
copy. The source run is never modified. C8 comes from the source run's final result.
"""
import argparse
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abr_boot_001 as h  # noqa: E402


def L(t):
    return t.replace("\r", "").split("\n")


def J(lines):
    return "\r\n".join(lines)


def C(l):
    return h.ANSI.sub("", l).strip()


def edit(fn):
    return lambda t: J(fn(L(t)))


def drop(pred):
    return edit(lambda ls: [l for l in ls if not pred(C(l))])


def sub(pred, a, b):
    return edit(lambda ls: [l.replace(a, b, 1) if pred(C(l)) else l for l in ls])


def regex_sub(pred, pattern, repl):
    return edit(lambda ls: [re.sub(pattern, repl, l, count=1) if pred(C(l)) else l for l in ls])


def after(pred, new):
    def f(ls):
        out = []
        for l in ls:
            out.append(l)
            if pred(C(l)):
                out.append(new)
        return out
    return edit(f)


def swap(pa, pb):
    def f(ls):
        ls = list(ls)
        i = next(k for k, l in enumerate(ls) if pa(C(l)))
        j = next(k for k, l in enumerate(ls) if pb(C(l)))
        ls[i], ls[j] = ls[j], ls[i]
        return ls
    return edit(f)


def move_before(pred, anchor):
    def f(ls):
        moved = [l for l in ls if pred(C(l))]
        rest = [l for l in ls if not pred(C(l))]
        i = next(k for k, l in enumerate(rest) if anchor(C(l)))
        return rest[:i] + moved + rest[i:]
    return edit(f)


init = lambda n: (lambda l: l.startswith(f"ABR|INIT|seq={n}|"))
events = lambda l: l.startswith("ABR|EVENTS|")
event = lambda n: (lambda l: l.startswith(f"ABR|EVENT|seq={n}|"))
op = lambda l: l == h.OPERATIONAL
tick = lambda n: (lambda l: l.startswith(f"ABR|TICK|uptime_s={n}|"))
ticks = lambda l: l.startswith("ABR|TICK|")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("out")
    a = ap.parse_args()
    src, out = Path(a.source), Path(a.out)
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    host0 = json.loads((src / "host.json").read_text())
    final0 = json.loads((src / "results.json.final").read_text())
    if final0.get("verdict") != "PASS" or final0.get("profile") != "0.31b" or host0.get("restart_mode") != "cold":
        raise SystemExit("REFUSED: the source must be a PASS run, profile 0.31b, cold restart")
    s1 = (src / "serial.log").read_bytes().decode("latin-1")
    s2 = (src / "serial-boot2.log").read_bytes().decode("latin-1")
    n_events = int(re.search(r"ABR\|EVENTS\|recorded=(\d+)\|", s1).group(1))
    timer_started = next(C(l) for l in L(s1) if "|code=TIMER_STARTED|" in C(l))
    memcheck_event = next(C(l) for l in L(s1) if "|code=MEMCHECK_PASS|" in C(l))
    I = None
    cases = {
        "baseline_unmutated": (I, I, "PASS"),
        # C10: lifecycle lines
        "init_transition_removed": (drop(init(4)), I, "FAIL"),
        "init_transitions_swapped": (swap(init(3), init(4)), I, "FAIL"),
        "init_seq_renumbered": (sub(init(5), "seq=5|", "seq=6|"), I, "FAIL"),
        "init_failed_transition_added": (after(op, "ABR|INIT|seq=8|from=OPERATIONAL|to=FAILED|reason=PANIC"), I, "FAIL"),
        "init_refusal_added": (after(init(2), "ABR|INIT|refused|from=MEMORY_OWNED|to=OPERATIONAL"), I, "FAIL"),
        "operational_without_its_transition": (drop(init(7)), I, "FAIL"),
        "operational_transition_after_state_line": (swap(init(7), op), I, "FAIL"),
        "init_wrong_target_state": (sub(init(6), "to=OWNERSHIP_VERIFIED", "to=OPERATIONAL"), I, "FAIL"),
        "init_line_with_extra_field": (sub(init(3), "to=MEMORY_VERIFIED", "to=MEMORY_VERIFIED|reason=X"), I, "FAIL"),
        # C10: event log
        "events_summary_removed": (drop(events), I, "FAIL"),
        "events_dropped_nonzero": (sub(events, "dropped=0|", "dropped=1|"), I, "FAIL"),
        "events_lost_reentrant_nonzero": (sub(events, "lost_reentrant=0", "lost_reentrant=1"), I, "FAIL"),
        "events_capacity_changed": (sub(events, "capacity=32|", "capacity=64|"), I, "FAIL"),
        "events_count_mismatch": (sub(events, f"recorded={n_events}|", f"recorded={n_events + 1}|"), I, "FAIL"),
        "event_record_removed": (drop(event(5)), I, "FAIL"),
        "event_seq_gap": (sub(event(n_events), f"seq={n_events}|", f"seq={n_events + 1}|"), I, "FAIL"),
        "fault_event_added": (edit(lambda ls: [l.replace(f"recorded={n_events}|", f"recorded={n_events + 1}|") for l in ls]
                                   + [f"ABR|EVENT|seq={n_events + 1}|uptime_ms=40|kind=FAULT|code=PANIC|arg=0x0"]), I, "FAIL"),
        "event_unknown_kind": (sub(event(2), "kind=MEMORY", "kind=NETWORK"), I, "FAIL"),
        "event_uptime_goes_back": (regex_sub(event(n_events), r"uptime_ms=\d+", "uptime_ms=1"), I, "FAIL"),
        "init_event_code_changed": (sub(event(1), "code=LOADER_VERIFIED", "code=MEMORY_OWNED"), I, "FAIL"),
        "memcheck_event_code_changed": (sub(lambda l: l == memcheck_event, "MEMCHECK_PASS", "MEMCHECK_FAIL"), I, "FAIL"),
        "timer_started_event_removed": (edit(lambda ls: [l for l in ls if C(l) != timer_started]), I, "FAIL"),
        "events_summary_before_operational": (move_before(events, op), I, "FAIL"),
        "event_line_malformed": (sub(event(3), "|arg=0x", "|arg=zz"), I, "FAIL"),
        "boot2_events_dropped_nonzero": (I, sub(events, "dropped=0|", "dropped=2|"), "FAIL"),
        "boot2_init_transition_removed": (I, drop(init(2)), "FAIL"),
        # C11: clock
        "heartbeat_reports_clock_anomaly": (sub(tick(7), "clock_anomalies=0", "clock_anomalies=1"), I, "FAIL"),
        "clock_anomaly_line_added": (after(tick(5), "ABR|CLOCK|anomaly=TSC_BACKWARD|counts=1000|uptime_ms=5000"), I, "FAIL"),
        "clock_degraded_line_added": (after(tick(5), "ABR|CLOCK|state=DEGRADED|reason=TSC_BACKWARD|uptime_claimed_accurate=false"), I, "FAIL"),
        "heartbeat_field_missing": (edit(lambda ls: [l.replace("|clock_anomalies=0", "") if ticks(C(l)) else l for l in ls]), I, "FAIL"),
        "boot2_clock_line_added": (I, after(tick(2), "ABR|CLOCK|anomaly=HEARTBEAT_GAP|from_s=2|to_s=99|skipped=96"), "FAIL"),
    }
    out.mkdir(parents=True)
    report = {"source_run": str(src), "profile": "0.31b", "cases": {}}
    for name, (f1, f2, expected) in cases.items():
        case = out / name
        case.mkdir()
        (case / "serial.log").write_bytes((f1(s1) if f1 else s1).encode("latin-1"))
        (case / "serial-boot2.log").write_bytes((f2(s2) if f2 else s2).encode("latin-1"))
        args = argparse.Namespace(run_id=f"mutation-{name}", stable_seconds=15, profile="0.31b", expect_memtest=False)
        result = h.judge(case / "serial.log", copy.deepcopy(host0), args)
        result["conditions"]["C8_evidence"] = final0["conditions"]["C8_evidence"]
        got = h.verdict(result)
        report["cases"][name] = {"expected": expected, "verdict": got, "ok": (got == "PASS") == (expected == "PASS"),
                                 "failed": sorted(c for c, v in result["conditions"].items() if v.get("pass") is False)}
    # profile handling: an unknown profile is never PASS
    res = h.judge(src / "serial.log", copy.deepcopy(host0), argparse.Namespace(run_id="profile", stable_seconds=15, profile="0.31c", expect_memtest=False))
    res["conditions"]["C8_evidence"] = final0["conditions"]["C8_evidence"]
    res["profile"] = "0.31c"
    got = h.verdict(res)
    report["cases"]["unknown_profile"] = {"expected": "FAIL", "verdict": got, "ok": got != "PASS", "failed": []}
    report["cases_total"] = len(report["cases"])
    report["all_ok"] = all(c["ok"] for c in report["cases"].values())
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    h.seal(out)
    for name, c in report["cases"].items():
        print(f"{'ok ' if c['ok'] else 'BAD'} {name:42s} expected={c['expected']} got={c['verdict']} failed={c['failed']}")
    print(f"{sum(c['ok'] for c in report['cases'].values())}/{report['cases_total']}", "ALL OK" if report["all_ok"] else "NOT ALL OK")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
