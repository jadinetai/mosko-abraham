"""ABRAHAM 0.31a harness self-test: the judge must fail closed.

  python -I tools/g031/judge_selftest.py <PASS run dir (profile 0.31a, cold restart)> <output dir>

Takes a real PASS run, applies ONE falsification at a time to COPIES of its evidence, re-judges
each with abr_boot_001.judge() + verdict() (profile 0.31a) and requires FAIL for every mutation
and PASS for the unmutated copy. The source run is never modified. C8 (the seal) is taken from
the source run's final result, so only the judge's own reading of the evidence is under test.

Covers handoff Step 5 "harness self-test": missing log, false serial banner, interrupted test,
missing timer opt-out when required (F-029-05), plus every 0.31a C9 item and every 0.29 G7
falsification.
"""
import argparse
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abr_boot_001 as h  # noqa: E402


def lines_of(text):
    return text.replace("\r", "").split("\n")


def join(lines):
    return "\r\n".join(lines)


def edit(fn):
    return lambda text: join(fn(lines_of(text)))


def drop_first(pred):
    def f(lines):
        out, done = [], False
        for l in lines:
            if not done and pred(h.ANSI.sub("", l).strip()):
                done = True
                continue
            out.append(l)
        return out
    return edit(f)


def drop_all(pred):
    return edit(lambda lines: [l for l in lines if not pred(h.ANSI.sub("", l).strip())])


def replace_line(pred, fn):
    return edit(lambda lines: [fn(l) if pred(h.ANSI.sub("", l).strip()) else l for l in lines])


def insert_after(pred, new):
    def f(lines):
        out = []
        for l in lines:
            out.append(l)
            if pred(h.ANSI.sub("", l).strip()):
                out.append(new)
        return out
    return edit(f)


def move_after_operational(pred):
    def f(lines):
        moved = [l for l in lines if pred(h.ANSI.sub("", l).strip())]
        rest = [l for l in lines if not pred(h.ANSI.sub("", l).strip())]
        i = next(k for k, l in enumerate(rest) if h.ANSI.sub("", l).strip() == h.OPERATIONAL)
        return rest[:i + 1] + moved + rest[i + 1:]
    return edit(f)


def truncate_after_ticks(n):
    def f(lines):
        out, seen = [], 0
        for l in lines:
            out.append(l)
            if h.ANSI.sub("", l).strip().startswith("ABR|TICK"):
                seen += 1
                if seen == n:
                    break
        return out
    return edit(f)


is_memcheck_timer = lambda l: l.startswith("ABR|MEMCHECK|stage=timer|")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("out")
    # 0.31b: the same falsifications can be judged under profile 0.31b (default stays 0.31a). 0.32 adds profile 0.32.
    ap.add_argument("--profile", default="0.31a", choices=("0.31a", "0.31b", "0.32", "0.32b"))
    a = ap.parse_args()
    src, out = Path(a.source), Path(a.out)
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    host0 = json.loads((src / "host.json").read_text())
    final0 = json.loads((src / "results.json.final").read_text())
    if final0.get("verdict") != "PASS" or final0.get("profile") != a.profile or host0.get("restart_mode") != "cold":
        raise SystemExit(f"REFUSED: the source must be a PASS run, profile {a.profile}, cold restart")
    s1 = (src / "serial.log").read_bytes().decode("latin-1")
    s2 = (src / "serial-boot2.log").read_bytes().decode("latin-1")
    epoch1 = re.search(r"boot_epoch=([0-9a-f]{16})", s1).group(1)
    epoch2 = re.search(r"boot_epoch=([0-9a-f]{16})", s2).group(1)

    def host_set(path, value):
        def f(hd):
            hd[path] = value
            return hd
        return f

    def opt_fail(key):
        def f(hd):
            hd[key] = {"ok": False, "error": 5, "control_mask": 4, "state_mask": 0}
            return hd
        return f

    I = None  # unchanged
    cases = {
        # --- control
        "baseline_unmutated": (I, I, I, "PASS"),
        # --- handoff Step 5 harness self-tests
        "missing_serial_log_boot1": (lambda t: "", I, I, "FAIL"),
        "missing_serial_log_boot2": (I, lambda t: "", I, "FAIL"),
        "false_banner_name": (replace_line(lambda l: l.startswith("ABR|BANNER"), lambda l: l.replace("name=ABRAHAM", "name=ABRAHAM-FAKE")), I, I, "FAIL"),
        "false_human_banner": (replace_line(lambda l: l.startswith("ABRAHAM | MOSKO"), lambda l: l.replace("ABR-BOOT-001", "NOT-ABRAHAM")), I, I, "FAIL"),
        "banner_without_status": (replace_line(lambda l: l.startswith("ABR|BANNER"), lambda l: l.split("|status=")[0]), I, I, "FAIL"),
        "interrupted_after_3_ticks": (truncate_after_ticks(3), I, I, "FAIL"),
        "opt_out_failed_boot1": (I, I, opt_fail("timer_throttling_opt_out_boot1"), "FAIL"),
        "opt_out_failed_boot2": (I, I, opt_fail("timer_throttling_opt_out_boot2"), "FAIL"),
        "opt_out_result_missing": (I, I, host_set("timer_throttling_opt_out_boot1", None), "FAIL"),
        # --- 0.31a C9 (frame ownership)
        "no_allocator_state_line": (drop_all(lambda l: l.startswith("ABR|MEM|state=")), I, I, "FAIL"),
        "allocator_not_ready": (replace_line(lambda l: l.startswith("ABR|MEM|state="), lambda l: l.replace("state=READY", "state=EMPTY")), I, I, "FAIL"),
        "map_anomaly_reported": (replace_line(lambda l: l.startswith("ABR|MEM|state="), lambda l: l.replace("anomalies=0|", "anomalies=1|")), I, I, "FAIL"),
        "no_memcheck_init": (drop_all(lambda l: l.startswith("ABR|MEMCHECK|stage=init|")), I, I, "FAIL"),
        "no_memcheck_timer": (drop_all(is_memcheck_timer), I, I, "FAIL"),
        "memcheck_timer_failed": (replace_line(is_memcheck_timer, lambda l: l.replace("violations=0|result=PASS", "violations=1|result=FAIL")), I, I, "FAIL"),
        "memcheck_result_pass_but_violations": (replace_line(is_memcheck_timer, lambda l: l.replace("violations=0|", "violations=2|")), I, I, "FAIL"),
        "violation_line_injected": (insert_after(is_memcheck_timer, "ABR|MEMCHECK|stage=timer|violation=PT_FRAME_FREE|frame=0xbf6a000"), I, I, "FAIL"),
        "created_table_not_pinned": (replace_line(is_memcheck_timer, lambda l: re.sub(r"pt_pinned=\d+", "pt_pinned=1", l)), I, I, "FAIL"),
        "report_only_build": (insert_after(is_memcheck_timer, "ABR|DIAG|memcheck_nonfatal|stage=timer|would_fault=FRAME_OWNERSHIP_COLLISION|continuing=DIAGNOSTIC_ONLY"), I, I, "FAIL"),
        "memcheck_only_after_operational": (move_after_operational(is_memcheck_timer), I, I, "FAIL"),
        "undeclared_memtest_summary": (insert_after(is_memcheck_timer, "ABR|MEMTEST|summary|allocated=1|result=PASS"), I, I, "FAIL"),
        "boot2_no_memcheck_timer": (I, drop_all(is_memcheck_timer), I, "FAIL"),
        "boot2_allocator_not_ready": (I, replace_line(lambda l: l.startswith("ABR|MEM|state="), lambda l: l.replace("state=READY", "state=FAULTED")), I, "FAIL"),
        # --- every 0.29 G7 falsification, still FAIL under the 0.31a judge
        "no_nasm_entry_line": (drop_first(lambda l: l == h.ENTRY), I, I, "FAIL"),
        "no_rust_kmain_line": (drop_first(lambda l: l == h.KMAIN), I, I, "FAIL"),
        "no_operational_boot1": (drop_first(lambda l: l == h.OPERATIONAL), I, I, "FAIL"),
        "no_banner_boot1": (drop_first(lambda l: l.startswith("ABR|BANNER")), I, I, "FAIL"),
        "fault_line_inserted": (lambda t: t + "\r\nABR|FAULT|vector=13|name=GENERAL_PROTECTION|error=0x0|rip=0x0\r\n", I, I, "FAIL"),
        "too_few_heartbeats": (drop_all(lambda l: l.startswith("ABR|TICK") and int(re.search(r"uptime_s=(\d+)", l).group(1)) > 5), I, I, "FAIL"),
        "heartbeat_gap": (drop_first(lambda l: l.startswith("ABR|TICK|uptime_s=7|")), I, I, "FAIL"),
        "loader_not_limine": (lambda t: t.replace("loader=Limine", "loader=Unknown"), I, I, "FAIL"),
        "no_firmware_boot_disk_start": (drop_all(lambda l: l.startswith("BdsDxe: starting Boot")), I, I, "FAIL"),
        "boot2_epoch_reused": (I, lambda t: t.replace(epoch2, epoch1), I, "FAIL"),
        "boot2_never_operational": (I, drop_first(lambda l: l == h.OPERATIONAL), I, "FAIL"),
        "guest_reset_event": (I, I, lambda hd: hd["qmp_events"].append({"event": "RESET", "data": {"guest": True, "reason": "guest-reset"}}) or hd, "FAIL"),
        "vm_not_running_after_window": (I, I, lambda hd: hd.update(status_after_window_1={"status": "paused"}) or hd, "FAIL"),
        "boot1_qemu_exit_nonzero": (I, I, lambda hd: hd.update(qemu_exit=1) or hd, "FAIL"),
    }
    out.mkdir(parents=True)
    report = {"source_run": str(src), "source_verdict": final0["verdict"], "profile": a.profile, "cases": {}}
    for name, (f1, f2, fh, expected) in cases.items():
        case = out / name
        case.mkdir()
        (case / "serial.log").write_bytes((f1(s1) if f1 else s1).encode("latin-1"))
        (case / "serial-boot2.log").write_bytes((f2(s2) if f2 else s2).encode("latin-1"))
        hd = copy.deepcopy(host0)
        if fh:
            hd = fh(hd)
        args = argparse.Namespace(run_id=f"mutation-{name}", stable_seconds=15, profile=a.profile, expect_memtest=False)
        result = h.judge(case / "serial.log", hd, args)
        result["conditions"]["C8_evidence"] = final0["conditions"]["C8_evidence"]
        got = h.verdict(result)
        failed = sorted(c for c, v in result["conditions"].items() if v.get("pass") is False)
        report["cases"][name] = {"expected": expected, "verdict": got, "ok": got == expected, "failed": failed}
    report["cases_total"] = len(cases)
    report["all_ok"] = all(c["ok"] for c in report["cases"].values())
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    h.seal(out)
    for name, c in report["cases"].items():
        print(f"{'ok ' if c['ok'] else 'BAD'} {name:38s} expected={c['expected']} got={c['verdict']} failed={c['failed']}")
    print(f"{sum(c['ok'] for c in report['cases'].values())}/{len(cases)}", "ALL OK" if report["all_ok"] else "NOT ALL OK")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
