"""ABRAHAM 0.32b judge self-test for the hardened condition C12 (services; D-ABR-020, audit finding 4).

  python -I -B tools/g032b/judge_selftest_032b.py <PASS run of the 0.32b kernel, profile 0.32b, cold restart> <output dir>

The 0.32 self-test (tools/g032/judge_selftest_032.py, corrected after ABR-0.32-J001) with its 42 cases judged under
profile 0.32b, plus 16 cases for the 0.32b hardening:
  - impossible readiness counts;
  - contradictory state reports;
  - unchecked or inconsistent durations;
  - the probe_timing claim.
The rules of the 0.32 self-test follow, unchanged:

Applies one falsification at a time to COPIES of a real run and judges each copy with the harness under profile 0.32.
Unlike the 0.31b self-test, a case is correct only if it fails FOR ITS INTENDED REASON (0.31 lesson):
  - the named condition is among the failed ones (and, for cases marked `only`, it is the only failed one),
  - the named C12 item(s) are false in the named boot.
The unmutated copy must PASS, and the end-of-capture control (a status round cut at the very end of boot 1) must PASS
with the cut reported. The source run is never modified; C8 is taken from its sealed final result.
"""
import argparse
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
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


def sub_nth(pred, n, a, b):
    """Replace a by b in the n-th line (0-based) matching pred."""
    def f(ls):
        out, k = [], 0
        for l in ls:
            if pred(C(l)):
                if k == n:
                    assert a in l, (a, l)
                    l = l.replace(a, b, 1)
                k += 1
            out.append(l)
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


def after(pred, new, n=0):
    def f(ls):
        out, k = [], 0
        for l in ls:
            out.append(l)
            if pred(C(l)):
                if k == n:
                    out.append(new)
                k += 1
        return out
    return edit(f)


def dup(pred, n=0):
    def f(ls):
        out, k = [], 0
        for l in ls:
            out.append(l)
            if pred(C(l)):
                if k == n:
                    out.append(l)
                k += 1
        return out
    return edit(f)


def move_before(pred, anchor):
    def f(ls):
        moved = [l for l in ls if pred(C(l))]
        rest = [l for l in ls if not pred(C(l))]
        i = next(k for k, l in enumerate(rest) if anchor(C(l)))
        return rest[:i] + moved + rest[i:]
    return edit(f)


def swap(pa, pb):
    def f(ls):
        ls = list(ls)
        i = next(k for k, l in enumerate(ls) if pa(C(l)))
        j = next(k for k, l in enumerate(ls) if pb(C(l)))
        ls[i], ls[j] = ls[j], ls[i]
        return ls
    return edit(f)


def drop_round(n):
    """Drop the n-th complete status round (3 lines)."""
    def f(ls):
        idx = [k for k, l in enumerate(ls) if C(l).startswith("ABR|SVCSTATUS|")]
        gone = set(idx[3 * n:3 * n + 3])
        return [l for k, l in enumerate(ls) if k not in gone]
    return edit(f)


def dup_round(n):
    def f(ls):
        idx = [k for k, l in enumerate(ls) if C(l).startswith("ABR|SVCSTATUS|")]
        r = idx[3 * n:3 * n + 3]
        return ls[:r[-1] + 1] + [ls[k] for k in r] + ls[r[-1] + 1:]
    return edit(f)


def end_cut(complete_lines):
    """End-of-capture control (corrected after ABR-0.32-J001, TR-0037): keep every line of boot 1, remove only the
    source's own end-of-capture fragment if it has one, then end the capture inside a NEW status round: `complete_lines`
    complete lines of it (0 or 1), then one line cut in half. Nothing else (no heartbeat) is removed. The first version
    cut the log inside the last complete round and so also removed the heartbeats printed after it (C5 then failed)."""
    def f(ls):
        ls = list(ls)
        while ls and C(ls[-1]) == "":
            ls.pop()
        if ls and C(ls[-1]).startswith("ABR|SVCSTATUS|") and not h.SVC_STATUS.match(C(ls[-1])):
            ls.pop()
        # 0.33 (ABR-0.33-J001): the source's own final round may itself be incomplete (its capture ended inside it);
        # drop its complete lines too, so the new round starts on a round boundary, after the last complete round
        k, trailing = len(ls) - 1, 0
        while k >= 0 and h.SVC_STATUS.match(C(ls[k])):
            trailing, k = trailing + 1, k - 1
        for _ in range(trailing % len(h.SVC_TABLE)):
            ls.pop()
        last_round = [l for l in ls if h.SVC_STATUS.match(C(l))][-3:]
        tail = last_round[:complete_lines]
        cut = last_round[complete_lines]
        return ls + tail + [cut[:len(cut) // 2]]
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


def cut_in_the_middle():
    """A cut status line that is NOT at the end of capture."""
    def f(ls):
        idx = [k for k, l in enumerate(ls) if C(l).startswith("ABR|SVCSTATUS|")]
        k = idx[4]  # svc.counter line of round 2
        return ls[:k] + [ls[k][:len(ls[k]) // 2]] + ls[k + 1:]
    return edit(f)


svc = lambda l: l.startswith("ABR|SVC")
reg = lambda l: l.startswith("ABR|SVC|registry=")
ready = lambda l: l.startswith("ABR|SVC|id=svc.counter|ready=PASS|")
c_run = lambda l: l.startswith("ABR|SVC|id=svc.counter|seq=2|")
c_start = lambda l: l.startswith("ABR|SVC|id=svc.counter|seq=1|")
withheld = lambda l: l.startswith("ABR|SVC|id=svc.netmon|start=WITHHELD")
st = lambda name: (lambda l: l.startswith(f"ABR|SVCSTATUS|id={name}|"))
dump = lambda l: l.startswith("ABR|SVCEVENTS|")
ev = lambda code: (lambda l: l.startswith("ABR|SVCEVENT|") and f"|code={code}|" in l)
op = lambda l: l == h.OPERATIONAL
init7 = lambda l: l.startswith("ABR|INIT|seq=7|")
events_line = lambda l: l.startswith("ABR|EVENTS|")


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
    if final0.get("verdict") != "PASS" or host0.get("restart_mode") != "cold" or final0.get("profile") != "0.32b":
        raise SystemExit("REFUSED: the source must be a PASS run, profile 0.32b, with a cold restart")
    s1 = (src / "serial.log").read_bytes().decode("latin-1")
    s2 = (src / "serial-boot2.log").read_bytes().decode("latin-1")
    c_values = [int(m) for m in re.findall(r"SVCSTATUS\|id=svc\.counter\|[^\r\n]*\|value=(\d+)\|", s1)]
    I = None
    C12 = "C12_services"
    # name: (boot1 edit, boot2 edit, expected verdict, failing condition, boot, items, only)
    cases = {
        "baseline_unmutated": (I, I, "PASS", None, None, [], False),
        "end_of_capture_cut_control": (end_cut(0), I, "PASS", None, None, [], False),
        "end_of_capture_partial_round_control": (end_cut(1), I, "PASS", None, None, [], False),
        "running_without_readiness": (drop(ready), I, "FAIL", C12, "boot1", ["counter_running_only_after_readiness"], True),
        "readiness_counts_unequal": (sub_nth(ready, 0, "|kernel_units=1|", "|kernel_units=2|"), I, "FAIL", C12, "boot1",
                                     ["counter_running_only_after_readiness"], True),
        "running_before_operational": (move_before(c_run, op), I, "FAIL", C12, "boot1",
                                       ["nothing_before_the_operational_event_printout"], False),
        "service_line_before_operational": (after(init7, "ABR|SVC|id=svc.counter|seq=1|from=DECLARED|to=STARTING"), I, "FAIL", C12,
                                            "boot1", ["nothing_before_the_operational_event_printout"], False),
        "service_line_before_event_printout": (move_before(reg, events_line), I, "FAIL", C12, "boot1",
                                               ["nothing_before_the_operational_event_printout"], False),
        "netmon_shown_available": (sub_nth(st("svc.netmon"), 1, "status=UNAVAILABLE", "status=AVAILABLE"), I, "FAIL", C12, "boot1",
                                   ["adapter_and_netmon_unavailable_not_installed"], True),
        "netmon_started": (edit(lambda ls: [l if not withheld(C(l)) else "ABR|SVC|id=svc.netmon|seq=1|from=DECLARED|to=STARTING"
                                            for l in ls]), I, "FAIL", C12, "boot1", ["netmon_withheld_by_adapter"], False),
        "adapter_started": (after(c_start, "ABR|SVC|id=dev.net0|seq=1|from=DECLARED|to=STARTING"), I, "FAIL", C12, "boot1",
                            ["adapter_skipped_as_not_installed"], False),
        "reason_is_a_kernel_diagnostic_code": (sub_nth(st("svc.counter"), 1, "reason=NONE", "reason=FRAME_DOUBLE_RELEASE"), I, "FAIL",
                                               C12, "boot1", ["reasons_appendix_a_or_none_only"], True),
        "reason_made_up": (sub_nth(st("dev.net0"), 0, "reason=NOT_INSTALLED", "reason=NOT_PLUGGED_IN"), I, "FAIL", C12, "boot1",
                           ["reasons_appendix_a_or_none_only"], True),
        "free_text_in_a_status": (regex_nth(st("svc.counter"), 1, r"$", "|note=all good"), I, "FAIL", C12, "boot1",
                                  ["every_service_line_well_formed"], True),
        "compromise_suspected": (sub_nth(st("svc.counter"), 1, "compromise=NONE_KNOWN", "compromise=SUSPECTED"), I, "FAIL", C12,
                                 "boot1", ["compromise_none_known_everywhere"], True),
        "counter_flat": (regex_nth(st("svc.counter"), 2, r"value=\d+\|steps=\d+",
                                   f"value={c_values[1]}|steps={c_values[1] - 1}"), I, "FAIL", C12, "boot1",
                         ["counter_strictly_increasing"], True),
        "counter_too_slow": (regex_nth(st("svc.counter"), 2, r"value=\d+\|steps=\d+",
                                       f"value={c_values[1] + 10}|steps={c_values[1] + 9}"), I, "FAIL", C12, "boot1",
                             ["counter_strictly_increasing"], True),
        "counter_above_its_wakes": (regex_nth(st("svc.counter"), 1, r"value=\d+\|steps=\d+", "value=99999|steps=99998"), I, "FAIL",
                                    C12, "boot1", ["counter_never_above_its_possible_wakes"], False),
        "counter_value_not_steps_plus_one": (regex_nth(st("svc.counter"), 1, r"steps=\d+", "steps=7"), I, "FAIL", C12, "boot1",
                                             ["counter_value_is_steps_plus_one"], True),
        "registry_line_duplicated": (dup(reg), I, "FAIL", C12, "boot1", ["registry_once_in_dependency_order"], True),
        "registry_line_missing": (drop(reg), I, "FAIL", C12, "boot1", ["registry_once_in_dependency_order"], True),
        "registry_wrong_order": (sub_nth(reg, 0, "order=dev.net0,svc.counter,svc.netmon", "order=svc.counter,dev.net0,svc.netmon"), I,
                                 "FAIL", C12, "boot1", ["registry_once_in_dependency_order"], True),
        "available_on_a_degraded_clock": (sub_nth(st("svc.counter"), 1, "clock=OK", "clock=DEGRADED"), I, "FAIL", C12, "boot1",
                                          ["counter_available_live_and_fresh"], True),
        "stale_observation_shown_available": (regex_nth(st("svc.counter"), 1, r"observed_at_ms=\d+", "observed_at_ms=1"), I, "FAIL", C12,
                                              "boot1", ["counter_available_live_and_fresh"], True),
        "event_record_code_changed": (sub_nth(ev("SVC_RUNNING"), 0, "code=SVC_RUNNING", "code=SVC_FAILED"), I, "FAIL", C12, "boot1",
                                      ["event_dump_matches_the_lines"], True),
        "event_record_arg_changed": (sub_nth(ev("SVC_STARTING"), 0, "arg=0x201", "arg=0x202"), I, "FAIL", C12, "boot1",
                                     ["event_dump_matches_the_lines"], True),
        "event_dump_dropped_records": (sub_nth(dump, 0, "|dropped=0|", "|dropped=1|"), I, "FAIL", C12, "boot1",
                                       ["event_dump_counts_consistent"], True),
        "event_dump_missing": (drop(dump), I, "FAIL", C12, "boot1", ["event_dump_once_after_the_start_phase"], False),
        "event_records_out_of_order": (swap(ev("SVC_STARTING"), ev("SVC_RUNNING")), I, "FAIL", C12, "boot1",
                                       ["event_dump_counts_consistent"], False),
        "event_record_removed": (drop(ev("SVC_START_WITHHELD")), I, "FAIL", C12, "boot1", ["event_dump_counts_consistent"], False),
        "round_line_missing_mid_log": (edit(lambda ls: (lambda idx: [l for k, l in enumerate(ls) if k != idx[4]])(
            [k for k, l in enumerate(ls) if C(l).startswith("ABR|SVCSTATUS|")])), I, "FAIL", C12, "boot1",
            ["status_rounds_complete_in_table_order"], False),
        "round_missing": (drop_round(1), I, "FAIL", C12, "boot1", ["status_rounds_every_5_s"], True),
        "round_flood": (dup_round(1), I, "FAIL", C12, "boot1", ["status_rounds_every_5_s"], False),
        "cut_line_not_at_the_end": (cut_in_the_middle(), I, "FAIL", C12, "boot1", ["every_service_line_well_formed"], False),
        "query_line_in_production": (after(c_run, "ABR|SVCQUERY|op=status|target=svc.counter|result=OK|status=AVAILABLE|reason=NONE"),
                                     I, "FAIL", C12, "boot1", ["every_service_line_well_formed"], True),
        "overrun_line_added": (after(c_run, "ABR|SVC|id=svc.counter|overrun|elapsed_us=5000|budget_us=1000|consecutive=1"
                                            "|diag=SVC_STEP_OVERRUN"), I, "FAIL", C12, "boot1", ["no_refusal_failure_or_overrun"], False),
        "unregistered_diag_code": (sub_nth(c_run, 0, "to=RUNNING", "to=RUNNING|diag=SVC_NOT_A_CODE"), I, "FAIL", C12, "boot1",
                                   ["diag_codes_registered"], False),
        "truncated_log_after_operational": (edit(lambda ls: ls[:ls.index(next(l for l in ls if C(l) == h.OPERATIONAL)) + 2]), I,
                                            "FAIL", C12, "boot1", ["registry_once_in_dependency_order"], False),
        "boot2_reason_made_up": (I, sub_nth(st("svc.netmon"), 0, "reason=NOT_INSTALLED", "reason=MADE_UP"), "FAIL", C12, "boot2",
                                 ["reasons_appendix_a_or_none_only"], True),
        "boot2_registry_missing": (I, drop(reg), "FAIL", C12, "boot2", ["registry_once_in_dependency_order"], True),
        "boot2_counter_not_ready": (I, drop(ready), "FAIL", C12, "boot2", ["counter_running_only_after_readiness"], True),
        # ---- 0.32b (audit finding 4): impossible readiness counts
        "f4_ready_counts_above_the_budget": (regex_nth(ready, 0, r"probe_units=\d+\|kernel_units=\d+\|observed=\d+",
                                                       "probe_units=5|kernel_units=5|observed=5"), I, "FAIL", C12, "boot1",
                                             ["readiness_counts_possible"], True),
        "f4_ready_counts_above_the_first_value": (regex_nth(ready, 0, r"probe_units=\d+\|kernel_units=\d+\|observed=\d+",
                                                            "probe_units=2|kernel_units=2|observed=2"), I, "FAIL", C12, "boot1",
                                                  ["readiness_counts_possible", "counter_value_is_steps_plus_one"], True),
        # ---- contradictory state reports
        "f4_start_lines_out_of_dependency_order": (move_before(withheld, lambda l: l.startswith("ABR|SVC|id=dev.net0|start=SKIPPED")),
                                                   I, "FAIL", C12, "boot1", ["start_lines_in_dependency_order"], True),
        "f4_static_entries_disagree_on_the_round_time": (regex_nth(st("svc.netmon"), 1, r"observed_at_ms=(\d+)",
                                                                   lambda m: f"observed_at_ms={int(m.group(1)) + 700}"),
                                                         I, "FAIL", C12, "boot1", ["round_entries_agree_on_the_time"], True),
        "f4_event_time_after_the_status_round": (regex_nth(ev("SVC_RUNNING"), 0, r"uptime_ms=\d+", "uptime_ms=99999"), I, "FAIL", C12,
                                                 "boot1", ["event_times_consistent"], True),
        "f4_status_state_contradicts_a_later_transition": (after(st("svc.counter"), "ABR|SVC|id=svc.counter|seq=3|from=RUNNING|to=STOPPING"),
                                                           I, "FAIL", C12, "boot1",
                                                           ["status_lines_consistent_with_transitions_mapping_and_clock"], False),
        "f4_clock_field_contradicts_the_clock_lines": (after(st("svc.netmon"), "ABR|CLOCK|state=DEGRADED|reason=TSC_BACKWARD|"
                                                                               "uptime_claimed_accurate=false"), I, "FAIL", C12, "boot1",
                                                       ["status_lines_consistent_with_transitions_mapping_and_clock"], False),
        "f4_status_fields_impossible_for_the_state": (sub_nth(st("svc.netmon"), 1, "liveness=UNKNOWN", "liveness=LOST"), I, "FAIL", C12,
                                                      "boot1", ["status_lines_consistent_with_transitions_mapping_and_clock"], True),
        # ---- unchecked or inconsistent durations
        "f4_probe_duration_far_over_budget": (regex_nth(ready, 0, r"probe_us=\d+", "probe_us=999999"), I, "FAIL", C12, "boot1",
                                              ["probe_duration_measured_and_in_budget"], True),
        "f4_probe_duration_missing": (regex_nth(ready, 0, r"probe_us=\d+", "probe_us=NONE"), I, "FAIL", C12, "boot1",
                                      ["probe_duration_measured_and_in_budget"], True),
        "f4_probe_timing_contradicts_its_duration": (regex_nth(ready, 0, r"probe_us=\d+", "probe_us=5000"), I, "FAIL", C12, "boot1",
                                                     ["probe_duration_measured_and_in_budget"], True),
        "f4_probe_timing_missing": (sub_nth(ready, 0, "|probe_timing=IN_BUDGET", ""), I, "FAIL", C12, "boot1",
                                    ["probe_duration_measured_and_in_budget"], True),
        "f4_probe_overrun_claimed_but_available": (sub_nth(ready, 0, "probe_timing=IN_BUDGET", "probe_timing=OVERRUN"), I, "FAIL", C12,
                                                   "boot1", ["probe_duration_measured_and_in_budget"], True),
        "f4_event_time_goes_backwards": (swap_uptimes(ev("SVC_REGISTRY_OK"), ev("SVC_START_WITHHELD")), I, "FAIL", C12, "boot1",
                                         ["event_times_consistent"], True),
        "f4_event_time_before_the_operational_records": (edit(lambda ls: [re.sub(r"uptime_ms=\d+", "uptime_ms=0", l, count=1)
                                                                          if C(l).startswith("ABR|SVCEVENT|") else l for l in ls]),
                                                         I, "FAIL", C12, "boot1", ["event_times_consistent"], True),
        "f4_round_times_shifted_against_heartbeats": (edit(lambda ls: [re.sub(r"observed_at_ms=(\d+)",
                                                                              lambda m: f"observed_at_ms={int(m.group(1)) + 3000}", l, count=1)
                                                                       if C(l).startswith("ABR|SVCSTATUS|") else l for l in ls]),
                                                      I, "FAIL", C12, "boot1", ["status_rounds_between_their_heartbeats"], True),
    }
    out.mkdir(parents=True)
    report = {"source_run": str(src), "profile": "0.32b", "cases": {}}

    def judge(t1, t2, profile="0.32b"):
        args = argparse.Namespace(run_id="mutation", stable_seconds=15, profile=profile, expect_memtest=False)
        res = h.judge(t1, copy.deepcopy(host0), args)
        res["conditions"]["C8_evidence"] = final0["conditions"]["C8_evidence"]
        res["profile"] = profile
        return res

    for name, (f1, f2, expected, cond, boot, items, only) in cases.items():
        case = out / name
        case.mkdir()
        (case / "serial.log").write_bytes((f1(s1) if f1 else s1).encode("latin-1"))
        (case / "serial-boot2.log").write_bytes((f2(s2) if f2 else s2).encode("latin-1"))
        res = judge(case / "serial.log", case / "serial-boot2.log")
        got = h.verdict(res)
        failed = sorted(c for c, v in res["conditions"].items() if v.get("pass") is False)
        c12 = res["conditions"].get(C12, {})
        false_items = {b: sorted(k for k, v in c12.get(b, {}).get("items", {}).items() if not v) for b in ("boot1", "boot2")}
        if expected == "PASS":
            ok = got == "PASS"
        else:
            ok = (got != "PASS" and cond in failed and (not only or failed == [cond])
                  and all(i in false_items[boot] for i in items))
        entry = {"expected": expected, "verdict": got, "ok": ok, "failed_conditions": failed, "false_items": false_items,
                 "intended": {"condition": cond, "boot": boot, "items": items, "only_this_condition": only}}
        if name.startswith("end_of_capture_"):
            eoc = c12.get("boot1", {}).get("end_of_capture") or {}
            entry["end_of_capture_boot1"] = eoc
            want_partial = 1 if name == "end_of_capture_partial_round_control" else 0
            entry["ok"] = ok and bool(eoc.get("cut_line")) and eoc.get("partial_final_round_lines") == want_partial
        report["cases"][name] = entry
    # profile handling: an unknown profile is never PASS
    # 0.33 (ABR-0.33-J001): "0.33" became a real profile; the unknown one must be a profile no tree defines
    res = judge(src / "serial.log", src / "serial-boot2.log", profile="0.99")
    got = h.verdict(res)
    report["cases"]["unknown_profile"] = {"expected": "FAIL", "verdict": got, "ok": got != "PASS"}
    report["cases_total"] = len(report["cases"])
    report["all_ok"] = all(c["ok"] for c in report["cases"].values())
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    h.seal(out)
    for name, c in report["cases"].items():
        print(f"{'ok ' if c['ok'] else 'BAD'} {name:40s} expected={c['expected']} got={c['verdict']} "
              f"failed={c.get('failed_conditions', [])} items={c.get('false_items', {})}")
    print(f"{sum(c['ok'] for c in report['cases'].values())}/{report['cases_total']}", "ALL OK" if report["all_ok"] else "NOT ALL OK")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
