"""ABRAHAM 0.32b (audit finding 4): falsified C12 evidence that a correct checker must reject.

  python -I -B tools/g032b/reproduce_032_c12.py --judge <tools dir> --source <PASS run, cold> --profile 0.32|0.32b
         --out <dir> [--require-correct]

Builds each case from COPIES of a real PASS run (the source is never modified) and judges it with the abr_boot_001.py
found in --judge (loaded read-only, so the unchanged 0.32 judge in work-0.32/tools can be put under test). The
expected answers are fixed here, before any run. The control must PASS. Every other case is falsified and must not
PASS. The cases, by the three parts of finding 4:
  impossible readiness counts   ready_counts_above_the_budget (5/5/5 for a 1-unit budget),
                                ready_counts_above_the_first_value (2/2/2, but the first status says value=1)
  contradictory state reports   start_lines_out_of_dependency_order (svc.netmon withheld by dev.net0 before dev.net0
                                was evaluated), static_entries_disagree_on_the_round_time (two entries of one
                                status round claim different evaluation times), event_time_after_the_status_round
                                (the RUNNING record is dated after the first status that reports RUNNING)
  unchecked durations           probe_duration_far_over_budget (probe_us=999999 with an AVAILABLE service),
                                probe_duration_missing (probe_us=NONE), event_time_goes_backwards,
                                event_time_before_the_operational_records, round_times_shifted_against_heartbeats
                                (every status time +3 s, so rounds claim times the heartbeats around them contradict)
Under the unchanged 0.32 judge each falsified case is expected to be judged PASS (the defect reproduced; run
ABR-0.32b-X002). The corrected judge must judge every one non-PASS (--require-correct exits 1 otherwise).
Standard library only.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path


def load_judge(tools_dir):
    spec = importlib.util.spec_from_file_location("judge_under_test", Path(tools_dir) / "abr_boot_001.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ANSI = re.compile(r"\x1b\[[0-9;=?]*[A-Za-z]")


def L(t):
    return t.replace("\r", "").split("\n")


def J(lines):
    return "\r\n".join(lines)


def C(l):
    return ANSI.sub("", l).strip()


def edit(fn):
    return lambda t: J(fn(L(t)))


def regex_first(pred, pattern, repl):
    def f(ls):
        out, done = [], False
        for l in ls:
            if not done and pred(C(l)):
                l2 = re.sub(pattern, repl, l, count=1)
                assert l2 != l, (pattern, l)
                l, done = l2, True
            out.append(l)
        assert done, pattern
        return out
    return edit(f)


def regex_nth(pred, n, pattern, repl):
    def f(ls):
        out, k = [], 0
        for l in ls:
            if pred(C(l)):
                if k == n:
                    l2 = re.sub(pattern, repl, l, count=1)
                    assert l2 != l, (pattern, l)
                    l = l2
                k += 1
            out.append(l)
        return out
    return edit(f)


def map_lines(pred, fn):
    return edit(lambda ls: [fn(l) if pred(C(l)) else l for l in ls])


def move_before(pred, anchor):
    def f(ls):
        moved = [l for l in ls if pred(C(l))]
        rest = [l for l in ls if not pred(C(l))]
        i = next(k for k, l in enumerate(rest) if anchor(C(l)))
        return rest[:i] + moved + rest[i:]
    return edit(f)


def swap_uptimes(pa, pb):
    def f(ls):
        ia = next(k for k, l in enumerate(ls) if pa(C(l)))
        ib = next(k for k, l in enumerate(ls) if pb(C(l)))
        ua = re.search(r"uptime_ms=(\d+)", ls[ia]).group(1)
        ub = re.search(r"uptime_ms=(\d+)", ls[ib]).group(1)
        assert ua != ub
        ls = list(ls)
        ls[ia] = ls[ia].replace(f"uptime_ms={ua}", f"uptime_ms={ub}", 1)
        ls[ib] = ls[ib].replace(f"uptime_ms={ub}", f"uptime_ms={ua}", 1)
        return ls
    return edit(f)


ready = lambda l: l.startswith("ABR|SVC|id=svc.counter|ready=PASS|")
svcevent = lambda code: (lambda l: l.startswith("ABR|SVCEVENT|") and f"|code={code}|" in l)
any_svcevent = lambda l: l.startswith("ABR|SVCEVENT|")
status = lambda l: l.startswith("ABR|SVCSTATUS|")
st = lambda name: (lambda l: l.startswith(f"ABR|SVCSTATUS|id={name}|"))
withheld = lambda l: l.startswith("ABR|SVC|id=svc.netmon|start=WITHHELD")
skipped = lambda l: l.startswith("ABR|SVC|id=dev.net0|start=SKIPPED")


def plus(ms):
    return lambda l: re.sub(r"observed_at_ms=(\d+)", lambda m: f"observed_at_ms={int(m.group(1)) + ms}", l, count=1)


def cases():
    I = None
    return {
        "control_unmutated": (I, "PASS", "control"),
        "ready_counts_above_the_budget": (regex_first(ready, r"probe_units=\d+\|kernel_units=\d+\|observed=\d+",
                                                      "probe_units=5|kernel_units=5|observed=5"), "FAIL", "impossible readiness counts"),
        "ready_counts_above_the_first_value": (regex_first(ready, r"probe_units=\d+\|kernel_units=\d+\|observed=\d+",
                                                           "probe_units=2|kernel_units=2|observed=2"), "FAIL", "impossible readiness counts"),
        "start_lines_out_of_dependency_order": (move_before(withheld, skipped), "FAIL", "contradictory state reports"),
        "static_entries_disagree_on_the_round_time": (regex_nth(st("svc.netmon"), 1, r"observed_at_ms=(\d+)",
                                                                lambda m: f"observed_at_ms={int(m.group(1)) + 700}"),
                                                      "FAIL", "contradictory state reports"),
        "event_time_after_the_status_round": (regex_first(svcevent("SVC_RUNNING"), r"uptime_ms=\d+", "uptime_ms=99999"),
                                              "FAIL", "contradictory state reports"),
        "probe_duration_far_over_budget": (regex_first(ready, r"probe_us=\d+", "probe_us=999999"), "FAIL", "unchecked durations"),
        "probe_duration_missing": (regex_first(ready, r"probe_us=\d+", "probe_us=NONE"), "FAIL", "unchecked durations"),
        "event_time_goes_backwards": (swap_uptimes(svcevent("SVC_REGISTRY_OK"), svcevent("SVC_START_WITHHELD")), "FAIL",
                                      "unchecked durations"),
        "event_time_before_the_operational_records": (map_lines(any_svcevent, lambda l: re.sub(r"uptime_ms=\d+", "uptime_ms=0", l, count=1)),
                                                      "FAIL", "unchecked durations"),
        "round_times_shifted_against_heartbeats": (map_lines(status, plus(3000)), "FAIL", "unchecked durations"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--require-correct", action="store_true")
    a = ap.parse_args()
    h = load_judge(a.judge)
    src, out = Path(a.source), Path(a.out)
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    host0 = json.loads((src / "host.json").read_text())
    final0 = json.loads((src / "results.json.final").read_text())
    if final0.get("verdict") != "PASS" or host0.get("restart_mode") != "cold":
        raise SystemExit("REFUSED: the source must be a PASS run with a cold restart")
    s1 = (src / "serial.log").read_bytes().decode("latin-1")
    s2 = (src / "serial-boot2.log").read_bytes().decode("latin-1")
    out.mkdir(parents=True)
    report = {"judge": str(Path(a.judge) / "abr_boot_001.py"),
              "judge_sha256": hashlib.sha256((Path(a.judge) / "abr_boot_001.py").read_bytes()).hexdigest(),
              "source_run": str(src), "profile": a.profile, "cases": {}}
    for name, (f1, correct, part) in cases().items():
        case = out / name
        case.mkdir()
        (case / "serial.log").write_bytes((f1(s1) if f1 else s1).encode("latin-1"))
        (case / "serial-boot2.log").write_bytes(s2.encode("latin-1"))
        args = argparse.Namespace(run_id=f"case-{name}", stable_seconds=15, profile=a.profile, expect_memtest=False)
        result = h.judge(case / "serial.log", copy.deepcopy(host0), args)
        result["conditions"]["C8_evidence"] = final0["conditions"]["C8_evidence"]
        result["profile"] = a.profile
        got = h.verdict(result)
        c12 = result["conditions"].get("C12_services", {}).get("boot1", {})
        report["cases"][name] = {"part_of_finding_4": part, "correct_answer": correct, "judge_answered": got,
                                 "judge_is_correct": (got == "PASS") == (correct == "PASS"),
                                 "failed_conditions": sorted(c for c, v in result["conditions"].items() if v.get("pass") is False),
                                 "c12_boot1_false_items": sorted(k for k, v in c12.get("items", {}).items() if not v)}
    report["summary"] = {"cases": len(report["cases"]),
                         "judge_correct": sum(c["judge_is_correct"] for c in report["cases"].values()),
                         "judge_wrong": sorted(k for k, c in report["cases"].items() if not c["judge_is_correct"])}
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    sums = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*")) if p.is_file()}
    (out / "RUN_SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n")
    for k, c in report["cases"].items():
        print(f"{'correct' if c['judge_is_correct'] else 'WRONG  '} {k:46s} must={c['correct_answer']} judge={c['judge_answered']} "
              f"{c['failed_conditions']} {c['c12_boot1_false_items']}")
    print(json.dumps(report["summary"], indent=1))
    return 1 if a.require_correct and report["summary"]["judge_wrong"] else 0


if __name__ == "__main__":
    sys.exit(main())
