"""ABRAHAM 0.31b observation probe: DIAGNOSTIC builds that must keep running, judged on their output.

  python -I -B tools/g031b/observe_probe.py --run-id <id> --qemu-dir <dir> --accel whpx|tcg --kernel <elf>
         --expect-kernel-sha256 <sha> --limine-efi <EFI> --expect tsc-backward|tsc-jump|map-overlap [--seconds 12]

--expect tsc-backward  (diag-tsc-backward, F-029-04) after heartbeat 3 the guard sees the TSC 2 s behind:
        exactly one ABR|CLOCK anomaly TSC_BACKWARD (0 < counts <= injected), one DEGRADED line with that
        reason, no other anomaly; heartbeat seconds stay consecutive (uptime neither falls nor wraps);
        clock_anomalies 0 before, 1 after; heartbeats continue; no fault.
--expect tsc-jump      (diag-tsc-jump, F-029-04) after heartbeat 3 the guard sees the TSC 1 h ahead:
        exactly one TSC_FORWARD_JUMP (counts >= injected) and one HEARTBEAT_GAP (skipped >= 3590), one
        DEGRADED line with reason TSC_FORWARD_JUMP; no flood (heartbeat lines bounded by the run time);
        heartbeats resume consecutive above 3600 s with clock_anomalies 2; no fault.
--expect map-overlap   (diag-map-overlap, F-031a-E04) a duplicate of the largest USABLE entry appended to
        the map: anomalies UNSORTED and USABLE_DUPLICATE for entry 33, allocator READY with 2 anomalies,
        both ownership checks PASS with 0 violations, no POOL_OUTSIDE_USABLE, no number at or above 2^40 in
        any MEMCHECK line (no wrapped subtraction), OPERATIONAL and heartbeats with clock_anomalies 0.
Common: kernel entered, no ABR|FAULT line, no guest reset, QEMU still running. Uses the harness's QEMU
command, staging and verified timer opt-out (paused start). Evidence: evidence/g031b/<run-id>/, sealed.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abr_boot_001 as h  # noqa: E402


def fields(body):
    return dict(part.split("=", 1) for part in body.split("|") if "=" in part)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--qemu-dir", required=True)
    p.add_argument("--accel", choices=("whpx", "tcg"), required=True)
    p.add_argument("--kernel", required=True)
    p.add_argument("--expect-kernel-sha256", required=True)
    p.add_argument("--limine-efi", required=True)
    p.add_argument("--expect", choices=("tsc-backward", "tsc-jump", "map-overlap"), required=True)
    p.add_argument("--seconds", type=int, default=12)
    args = p.parse_args()
    h.use_qemu(args.qemu_dir)
    kernel = Path(args.kernel).read_bytes()
    if hashlib.sha256(kernel).hexdigest() != args.expect_kernel_sha256.lower():
        print(f"REFUSED: kernel {args.kernel} has SHA-256 {hashlib.sha256(kernel).hexdigest()}, "
              f"expected {args.expect_kernel_sha256}; nothing was run")
        return 2
    run = h.EVIDENCE / "g031b" / args.run_id
    if run.exists():
        raise SystemExit(f"REFUSED: {run} exists")
    esp = run / "esp"
    (esp / "EFI" / "BOOT").mkdir(parents=True)
    (esp / "boot" / "limine").mkdir(parents=True)
    shutil.copyfile(args.limine_efi, esp / "EFI" / "BOOT" / "BOOTX64.EFI")
    (esp / "boot" / "abraham-kernel").write_bytes(kernel)
    conf = h.LIMINE_CONF.read_text(encoding="ascii").replace("{KERNEL_BLAKE2B}", hashlib.blake2b(kernel).hexdigest())
    (esp / "boot" / "limine" / "limine.conf").write_text(conf, encoding="ascii", newline="\n")
    shutil.copyfile(h.FW_VARS, run / "vars.fd")
    serial = run / "serial.log"
    port = h.free_port()
    cpu = "host" if args.accel == "whpx" else "max"
    command = h.qemu_command(args.accel, cpu, run, esp, port, serial) + ["-S"]
    meta = {"run_id": args.run_id, "label": "VM_MEASURED, DIAGNOSTIC observation build (never accepted)",
            "expect": args.expect, "accelerator": args.accel, "cpu_model": cpu,
            "qemu": h.first_line([str(h.QEMU), "--version"]), "qemu_executable_sha256": h.sha256(h.QEMU),
            "kernel": str(Path(args.kernel)), "kernel_sha256": hashlib.sha256(kernel).hexdigest(),
            "limine_efi_sha256": h.sha256(args.limine_efi), "qemu_command": command, "started_utc": h.utc()}
    t0 = time.monotonic()
    with open(run / "qemu-stderr.txt", "wb") as err:
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err)
        meta["timer_throttling_opt_out"] = h.opt_out_timer_throttling(proc.pid)
        qmp = h.Qmp(port, run / "qmp.jsonl", t0)
        qmp.command("cont")
        meta["operational"] = bool(h.wait_for(lambda: h.OPERATIONAL in h.serial_lines(serial), 120))
        time.sleep(args.seconds)
        meta["status"] = qmp.command("query-status").get("return")
        qmp.command("quit")
        meta["qemu_exit"] = proc.wait(timeout=20)
    meta["qmp_events"] = qmp.events
    meta["observed_seconds_after_operational"] = args.seconds

    lines = h.serial_lines(serial)
    ticks = [fields(l[len("ABR|TICK|"):]) for l in lines if l.startswith("ABR|TICK|")]
    secs = [int(t["uptime_s"]) for t in ticks]
    anoms = [fields(l[len("ABR|CLOCK|"):]) for l in lines if l.startswith("ABR|CLOCK|anomaly=")]
    degraded = [fields(l[len("ABR|CLOCK|"):]) for l in lines if l.startswith("ABR|CLOCK|state=DEGRADED")]
    diag = next((fields(l[len("ABR|DIAG|"):]) for l in lines if l.startswith("ABR|DIAG|injecting=")), {})
    opt = meta["timer_throttling_opt_out"]
    checks = {
        "timer_opt_out_verified": isinstance(opt, dict) and opt.get("ok") is True,
        "kernel_entered": h.ENTRY in lines,
        "operational": h.OPERATIONAL in lines,
        "no_fault": not any(l.startswith("ABR|FAULT") for l in lines),
        "no_guest_reset": not any(e.get("event") == "RESET" for e in meta["qmp_events"]),
        "qemu_running": (meta["status"] or {}).get("status") == "running",
    }
    if args.expect in ("tsc-backward", "tsc-jump"):
        injected = int(diag.get("counts", "0"))
        before = [int(t["clock_anomalies"]) for t in ticks if int(t["uptime_s"]) <= 3]
        checks["injection_after_third_heartbeat"] = diag.get("injecting") == args.expect.replace("-", "_") and injected > 0
        checks["no_anomaly_before_injection"] = bool(before) and set(before) == {0}
    if args.expect == "tsc-backward":
        back = [a for a in anoms if a.get("anomaly") == "TSC_BACKWARD"]
        after = [int(t["clock_anomalies"]) for t in ticks if int(t["uptime_s"]) > 4]
        checks.update({
            "one_backward_anomaly_only": len(anoms) == 1 and len(back) == 1,
            "backward_counts_plausible": len(back) == 1 and 0 < int(back[0]["counts"]) <= injected,
            "degraded_once_with_reason": len(degraded) == 1 and degraded[0].get("reason") == "TSC_BACKWARD",
            "heartbeat_seconds_consecutive": bool(secs) and secs == list(range(secs[0], secs[0] + len(secs))),
            "no_wrap_no_huge_uptime": bool(secs) and max(secs) < 1000,
            "anomaly_counted_afterwards": bool(after) and set(after) == {1},
            "heartbeat_continues": len([s for s in secs if s > 4]) >= args.seconds // 2,
        })
    elif args.expect == "tsc-jump":
        jump = [a for a in anoms if a.get("anomaly") == "TSC_FORWARD_JUMP"]
        gap = [a for a in anoms if a.get("anomaly") == "HEARTBEAT_GAP"]
        high = [s for s in secs if s >= 3600]
        after = [int(t["clock_anomalies"]) for t in ticks if int(t["uptime_s"]) >= 3600]
        checks.update({
            "one_jump_and_one_gap": len(anoms) == 2 and len(jump) == 1 and len(gap) == 1,
            "jump_counts_at_least_injected": len(jump) == 1 and int(jump[0]["counts"]) >= injected,
            "gap_reported_once_not_flooded": len(gap) == 1 and int(gap[0]["skipped"]) >= 3590,
            "degraded_once_with_reason": len(degraded) == 1 and degraded[0].get("reason") == "TSC_FORWARD_JUMP",
            "heartbeat_lines_bounded": len(ticks) <= args.seconds + 30,
            "resumes_consecutive_above_3600": bool(high) and high == list(range(high[0], high[0] + len(high))),
            "anomalies_counted_afterwards": bool(after) and set(after) == {2},
        })
    else:  # map-overlap
        state = next((fields(l[len("ABR|MEM|"):]) for l in lines if l.startswith("ABR|MEM|state=")), {})
        anomaly_lines = [fields(l[len("ABR|MEM|anomaly|"):]) for l in lines if l.startswith("ABR|MEM|anomaly|")]
        checks_lines = [l for l in lines if l.startswith("ABR|MEMCHECK|")]
        numbers = [int(x, 16) if x.startswith("0x") else int(x) for l in checks_lines for x in re.findall(r"=(0x[0-9a-f]+|\d+)", l)]
        summaries = [fields(l[len("ABR|MEMCHECK|"):]) for l in checks_lines if "|result=" in l and "|violation=" not in l]
        checks.update({
            "injection_announced": diag.get("injecting") == "map_overlap",
            "duplicate_and_unsorted_reported": {(a.get("entry"), a.get("code")) for a in anomaly_lines}
                                               == {("33", "UNSORTED"), ("33", "USABLE_DUPLICATE")},
            "allocator_ready_with_2_anomalies": state.get("state") == "READY" and state.get("anomalies") == "2",
            "both_checks_pass": [(s.get("stage"), s.get("violations"), s.get("result")) for s in summaries]
                                == [("init", "0", "PASS"), ("timer", "0", "PASS")],
            "no_pool_outside_usable": not any("POOL_OUTSIDE_USABLE" in l for l in lines),
            "no_violation_lines": not any("|violation=" in l for l in checks_lines),
            "no_wrapped_number": bool(numbers) and max(numbers) < (1 << 40),
            "heartbeats_clean": bool(ticks) and all(t.get("clock_anomalies") == "0" for t in ticks),
        })
    result = {"verdict": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "diag_line": diag,
              "clock_anomalies": anoms, "heartbeats": len(ticks), "first_seconds": secs[:6], "last_seconds": secs[-4:],
              "not_claimed": "behavior of this one injected condition on this VM only"}
    meta["ended_utc"] = h.utc()
    (run / "probe.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    (run / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    h.seal(run)
    print(json.dumps({"run": args.run_id, "verdict": result["verdict"],
                      "failed_checks": [k for k, v in checks.items() if not v], "anomalies": anoms,
                      "first_seconds": secs[:6], "last_seconds": secs[-4:]}))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
