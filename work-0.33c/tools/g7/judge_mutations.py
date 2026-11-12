"""G7: prove the harness judge fails closed. Takes a real PASS run, applies one falsification at a
time to COPIES of its evidence, re-judges each with abr_boot_001.judge(), and requires FAIL for
every mutation and PASS for the unmutated copy. The source run is never modified.

  python -I tools/g7/judge_mutations.py evidence/ABR-BOOT-001/ABR-0.29-G6-C001 evidence/g7/G7-J001
"""
import argparse
import copy
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abr_boot_001 as h  # noqa: E402

CORE = ["C1_loader", "C2_kernel_entered", "C3_operational", "C4_banner", "C5_no_crash", "C6_restart"]


def mutate_lines(text, fn):
    return "\r\n".join(fn(text.replace("\r", "").split("\n")))


def drop(pred, first_only=True):
    def f(lines):
        out, done = [], False
        for l in lines:
            if pred(l) and not (first_only and done):
                done = True
                continue
            out.append(l)
        return out
    return f


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    host0 = json.loads((src / "host.json").read_text())
    s1 = (src / "serial.log").read_bytes().decode("latin-1")
    s2 = (src / "serial-boot2.log").read_bytes().decode("latin-1")
    clean = lambda l: h.ANSI.sub("", l).strip()
    epoch1 = re.search(r"boot_epoch=([0-9a-f]{16})", s1).group(1)
    epoch2 = re.search(r"boot_epoch=([0-9a-f]{16})", s2).group(1)

    cases = {
        "baseline_unmutated": (lambda a: a, lambda b: b, lambda hd: hd, "PASS"),
        "no_nasm_entry_line": (lambda a: mutate_lines(a, drop(lambda l: clean(l) == h.ENTRY)), None, None, "FAIL"),
        "no_rust_kmain_line": (lambda a: mutate_lines(a, drop(lambda l: clean(l) == h.KMAIN)), None, None, "FAIL"),
        "no_operational_boot1": (lambda a: mutate_lines(a, drop(lambda l: clean(l) == h.OPERATIONAL)), None, None, "FAIL"),
        "no_banner_boot1": (lambda a: mutate_lines(a, drop(lambda l: clean(l).startswith("ABR|BANNER"))), None, None, "FAIL"),
        "fault_line_inserted": (lambda a: a + "\r\nABR|FAULT|vector=13|name=GENERAL_PROTECTION|error=0x0|rip=0x0\r\n", None, None, "FAIL"),
        "too_few_heartbeats": (lambda a: mutate_lines(a, drop(lambda l: clean(l).startswith("ABR|TICK") and
                                                             int(re.search(r"uptime_s=(\d+)", l).group(1)) > 5, False)), None, None, "FAIL"),
        "heartbeat_gap": (lambda a: mutate_lines(a, drop(lambda l: clean(l).startswith("ABR|TICK|uptime_s=7|"))), None, None, "FAIL"),
        "loader_not_limine": (lambda a: a.replace("loader=Limine", "loader=Unknown"), None, None, "FAIL"),
        "no_firmware_boot_disk_start": (lambda a: mutate_lines(a, drop(lambda l: clean(l).startswith("BdsDxe: starting Boot"), False)), None, None, "FAIL"),
        "boot2_epoch_reused": (None, lambda b: b.replace(epoch2, epoch1), None, "FAIL"),
        "boot2_never_operational": (None, lambda b: mutate_lines(b, drop(lambda l: clean(l) == h.OPERATIONAL)), None, "FAIL"),
        "guest_reset_event": (None, None, lambda hd: hd["qmp_events"].append(
            {"event": "RESET", "data": {"guest": True, "reason": "guest-reset"}}) or hd, "FAIL"),
        "vm_not_running_after_window": (None, None, lambda hd: hd.update(status_after_window_1={"status": "paused"}) or hd, "FAIL"),
        "boot1_qemu_exit_nonzero": (None, None, lambda hd: hd.update(qemu_exit=1) or hd, "FAIL"),
    }
    out.mkdir(parents=True)
    report = {"source_run": str(src), "cases": {}}
    for name, (f1, f2, fh, expected) in cases.items():
        case = out / name
        case.mkdir()
        (case / "serial.log").write_bytes((f1(s1) if f1 else s1).encode("latin-1"))
        (case / "serial-boot2.log").write_bytes((f2(s2) if f2 else s2).encode("latin-1"))
        hd = copy.deepcopy(host0)
        if fh:
            hd = fh(hd)
        args = argparse.Namespace(run_id=f"mutation-{name}", stable_seconds=15)
        result = h.judge(case / "serial.log", hd, args)
        verdict = "PASS" if all(result["conditions"][c]["pass"] for c in CORE) else "FAIL"
        failed = [c for c in CORE if not result["conditions"][c]["pass"]]
        report["cases"][name] = {"expected": expected, "verdict": verdict, "ok": verdict == expected, "failed": failed}
    report["all_ok"] = all(c["ok"] for c in report["cases"].values())
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    h.seal(out)
    for name, c in report["cases"].items():
        print(f"{'ok ' if c['ok'] else 'BAD'} {name:30s} expected={c['expected']} got={c['verdict']} failed={c['failed']}")
    print("ALL OK" if report["all_ok"] else "NOT ALL OK")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
