"""ABRAHAM 0.31b investigation: reproduce Echo findings F-031a-E01..E03 against a judge.

  python -I -B tools/g031b/reproduce_031a_findings.py --judge <tools dir> --source <PASS run> --out <dir> --profile 0.31a

Applies each falsification to COPIES of a real PASS run's serial logs and host record and judges them with
the abr_boot_001 module found in --judge (the 0.31a judge in work-0.31/tools, or the 0.31b judge later).
Each case says what a CORRECT judge must answer; the report shows what this judge answered. The source run
and the judged tools are never modified (run with -B: no bytecode is written next to the judge).
"""
import argparse
import copy
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


def L(t):
    return t.replace("\r", "").split("\n")


def J(lines):
    return "\r\n".join(lines)


def clean(h, l):
    return h.ANSI.sub("", l).strip()


def cases(h, s1):
    def edit(fn):
        return lambda t: J(fn(L(t)))

    def before(pred, new):
        def f(lines):
            out = []
            for l in lines:
                if pred(clean(h, l)):
                    out.append(new)
                out.append(l)
            return out
        return edit(f)

    def after(pred, new):
        def f(lines):
            out = []
            for l in lines:
                out.append(l)
                if pred(clean(h, l)):
                    out.append(new)
            return out
        return edit(f)

    def drop(pred):
        return edit(lambda lines: [l for l in lines if not pred(clean(h, l))])

    def sub(pred, a, b):
        return edit(lambda lines: [l.replace(a, b) if pred(clean(h, l)) else l for l in lines])

    def swap_init_timer(lines):
        i = next(k for k, l in enumerate(lines) if clean(h, l).startswith("ABR|MEMCHECK|stage=init|"))
        j = next(k for k, l in enumerate(lines) if clean(h, l).startswith("ABR|MEMCHECK|stage=timer|"))
        lines = list(lines)
        lines[i], lines[j] = lines[j], lines[i]
        return lines

    timer = lambda l: l.startswith("ABR|MEMCHECK|stage=timer|")
    pin = lambda l: l.startswith("ABR|MEMPIN|")
    op = lambda l: l == h.OPERATIONAL
    timer_line = next(clean(h, l) for l in L(s1) if timer(clean(h, l)))
    first_pin = next(clean(h, l) for l in L(s1) if pin(clean(h, l)))
    failed_timer = re.sub(r"violations=0\|result=PASS", "violations=1|result=FAIL", timer_line)

    def host_flag_false(hd):
        hd["timer_throttling_opt_out_enabled"] = False
        return hd

    def host_flag_false_no_records(hd):
        hd["timer_throttling_opt_out_enabled"] = False
        hd.pop("timer_throttling_opt_out_boot1", None)
        hd.pop("timer_throttling_opt_out_boot2", None)
        return hd

    def host_records_removed(hd):
        hd.pop("timer_throttling_opt_out_boot1", None)
        hd.pop("timer_throttling_opt_out_boot2", None)
        return hd

    def host_set(fn):
        def f(hd):
            fn(hd)
            return hd
        return f

    def drop_timeline(text):
        return host_set(lambda hd: hd.update(timeline=[e for e in hd["timeline"] if e.get("what") != text]))

    def move_pin_after_summary(lines):
        """The first MEMPIN line is taken out of its block and re-inserted after the timer summary."""
        out = []
        for l in lines:
            if clean(h, l) == first_pin:
                continue
            out.append(l)
            if timer(clean(h, l)):
                out.append(first_pin)
        return out

    N = None
    init_line = next(clean(h, l) for l in L(s1) if clean(h, l).startswith("ABR|MEMCHECK|stage=init|"))
    added = {
        # 0.31b additions: the stricter C0 rules
        "c0_boot1_ok_false": (N, N, host_set(lambda hd: hd["timer_throttling_opt_out_boot1"].update(ok=False)), "FAIL", "F-031a-E01 (0.31b)"),
        "c0_boot2_record_removed": (N, N, host_set(lambda hd: hd.pop("timer_throttling_opt_out_boot2")), "FAIL", "F-031a-E01 (0.31b)"),
        "c0_wrong_control_mask": (N, N, host_set(lambda hd: hd["timer_throttling_opt_out_boot1"].update(control_mask=1)), "FAIL", "F-031a-E01 (0.31b)"),
        "c0_flag_is_string_true": (N, N, host_set(lambda hd: hd.update(timer_throttling_opt_out_enabled="true")), "FAIL", "F-031a-E01 (0.31b)"),
        "c0_not_started_paused": (N, N, host_set(lambda hd: hd.update(qemu_command=[c for c in hd["qemu_command"] if c != "-S"])), "FAIL", "F-031a-E01 (0.31b)"),
        "c0_boot2_not_started_paused": (N, N, host_set(lambda hd: hd.update(qemu_command_boot2=[c for c in hd["qemu_command_boot2"] if c != "-S"])), "FAIL", "F-031a-E01 (0.31b)"),
        "c0_cont_mark_missing": (N, N, drop_timeline("cont sent (after timer opt-out)"), "FAIL", "F-031a-E01 (0.31b)"),
        "c0_boot2_cont_mark_missing": (N, N, drop_timeline("boot 2 cont sent (after timer opt-out)"), "FAIL", "F-031a-E01 (0.31b)"),
        # 0.31b additions: summary consistency and grammar
        "c9_tables_sum_wrong": (sub(timer, "pt_tables=11|", "pt_tables=12|"), N, N, "FAIL", "F-031a-E02 (0.31b)"),
        "c9_fail_with_zero_violations": (sub(timer, "result=PASS", "result=FAIL"), N, N, "FAIL", "F-031a-E02 (0.31b)"),
        "c9_pinned_differs_from_pt_pinned": (sub(timer, "|pinned=2|", "|pinned=3|"), N, N, "FAIL", "F-031a-E02 (0.31b)"),
        "c9_init_summary_removed": (drop(lambda l: l == init_line), N, N, "FAIL", "F-031a-E02 (0.31b)"),
        "c9_summary_field_reordered": (sub(timer, "|pinned=2|violations=0|", "|violations=0|pinned=2|"), N, N, "FAIL", "F-031a-E02 (0.31b)"),
        # 0.31b additions: pin timing and format
        "c9_pin_moved_after_its_summary": (edit(move_pin_after_summary), N, N, "FAIL", "F-031a-E03 (0.31b)"),
        "c9_pin_repeated_after_operational": (after(op, first_pin), N, N, "FAIL", "F-031a-E03 (0.31b)"),
        "c9_pin_misaligned_frame": (sub(lambda l: l == first_pin, "frame=0x100000", "frame=0x100008"), N, N, "FAIL", "F-031a-E03 (0.31b)"),
        "c9_pin_stage_label_wrong": (sub(lambda l: l == first_pin, "stage=timer", "stage=init"), N, N, "FAIL", "F-031a-E03 (0.31b)"),
        "c9_pin_line_malformed": (sub(lambda l: l == first_pin, "|free=false", "|free=no"), N, N, "FAIL", "F-031a-E03 (0.31b)"),
        "c9_pin_at_init_stage": (before(lambda l: l == init_line, first_pin.replace("stage=timer", "stage=init")), N, N, "FAIL", "F-031a-E03 (0.31b)"),
    }
    return {
        # name: (serial boot1, serial boot2, host, what a correct judge must say, finding)
        "control_unmodified": (N, N, N, "PASS", "control"),
        "e01_opt_out_flag_false": (N, N, host_flag_false, "FAIL", "F-031a-E01"),
        "e01_opt_out_flag_false_and_records_removed": (N, N, host_flag_false_no_records, "FAIL", "F-031a-E01"),
        "e01_records_removed_flag_true": (N, N, host_records_removed, "FAIL", "F-031a-E01 (already caught in 0.31a)"),
        "e02_failed_timer_summary_before_pass": (before(timer, failed_timer), N, N, "FAIL", "F-031a-E02"),
        "e02_duplicate_pass_timer_summary": (after(timer, timer_line), N, N, "FAIL", "F-031a-E02"),
        "e02_timer_summary_repeated_after_operational": (after(op, timer_line), N, N, "FAIL", "F-031a-E02"),
        "e02_failed_summary_after_operational": (after(op, failed_timer), N, N, "FAIL", "F-031a-E02"),
        "e02_init_and_timer_out_of_order": (edit(swap_init_timer), N, N, "FAIL", "F-031a-E02"),
        "e02_malformed_timer_summary_added": (after(timer, "ABR|MEMCHECK|stage=timer|pt_tables=11|result=PASS"), N, N, "FAIL", "F-031a-E02"),
        "e02_unknown_stage_summary": (after(timer, timer_line.replace("stage=timer", "stage=bogus")), N, N, "FAIL", "F-031a-E02"),
        "e02_boot2_failed_summary_before_pass": (N, before(timer, failed_timer), N, "FAIL", "F-031a-E02"),
        "e03_all_mempin_removed": (drop(pin), N, N, "FAIL", "F-031a-E03"),
        "e03_mempin_in_pool_and_free": (sub(pin, "in_pool=false|free=false", "in_pool=true|free=true"), N, N, "FAIL", "F-031a-E03"),
        "e03_mempin_free_only": (sub(lambda l: pin(l) and "frame=0x101000" in l, "free=false", "free=true"), N, N, "FAIL", "F-031a-E03"),
        "e03_mempin_duplicate_address": (after(lambda l: l == first_pin, first_pin), N, N, "FAIL", "F-031a-E03"),
        "e03_mempin_extra_frame": (after(lambda l: l == first_pin, first_pin.replace("frame=0x100000", "frame=0x102000")), N, N, "FAIL", "F-031a-E03"),
        "e03_mempin_wrong_owner": (sub(pin, "owner=PAGE_TABLE", "owner=MMIO"), N, N, "FAIL", "F-031a-E03"),
        "e03_boot2_mempin_removed": (N, drop(pin), N, "FAIL", "F-031a-E03"),
        **added,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--require-correct", action="store_true",
                    help="exit 1 unless the judge answers every case correctly (used for the corrected judge)")
    a = ap.parse_args()
    h = load_judge(a.judge)
    src, out = Path(a.source), Path(a.out)
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    host0 = json.loads((src / "host.json").read_text())
    final0 = json.loads((src / "results.json.final").read_text())
    s1 = (src / "serial.log").read_bytes().decode("latin-1")
    s2 = (src / "serial-boot2.log").read_bytes().decode("latin-1")
    out.mkdir(parents=True)
    report = {"judge": str(Path(a.judge) / "abr_boot_001.py"), "source_run": str(src), "profile": a.profile, "cases": {}}
    for name, (f1, f2, fh, correct, finding) in cases(h, s1).items():
        case = out / name
        case.mkdir()
        (case / "serial.log").write_bytes((f1(s1) if f1 else s1).encode("latin-1"))
        (case / "serial-boot2.log").write_bytes((f2(s2) if f2 else s2).encode("latin-1"))
        hd = fh(copy.deepcopy(host0)) if fh else copy.deepcopy(host0)
        (case / "host.json").write_text(json.dumps(hd, indent=1, sort_keys=True) + "\n")
        args = argparse.Namespace(run_id=f"case-{name}", stable_seconds=15, profile=a.profile, expect_memtest=False)
        result = h.judge(case / "serial.log", hd, args)
        result["conditions"]["C8_evidence"] = final0["conditions"]["C8_evidence"]
        got = h.verdict(result)
        # A falsified case is answered correctly by any verdict except PASS (FAIL, or
        # CONTROL_NOT_QUALIFYING for a run without the opt-out); the control must be exactly PASS.
        report["cases"][name] = {"finding": finding, "correct_answer": correct, "judge_answered": got,
                                 "judge_is_correct": (got == "PASS") == (correct == "PASS"),
                                 "failed_conditions": sorted(c for c, v in result["conditions"].items() if v.get("pass") is False)}
    report["summary"] = {"cases": len(report["cases"]),
                         "judge_correct": sum(c["judge_is_correct"] for c in report["cases"].values()),
                         "judge_wrong": sorted(k for k, c in report["cases"].items() if not c["judge_is_correct"])}
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    import hashlib
    sums = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob("*")) if p.is_file()}
    (out / "RUN_SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n")
    for k, c in report["cases"].items():
        print(f"{'correct' if c['judge_is_correct'] else 'WRONG  '} {k:46s} must={c['correct_answer']} judge={c['judge_answered']} {c['failed_conditions']}")
    print(json.dumps(report["summary"], indent=1))
    return 1 if a.require_correct and report["summary"]["judge_wrong"] else 0


if __name__ == "__main__":
    sys.exit(main())
