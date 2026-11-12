"""ABRAHAM VM LAUNCHER 0.33: verify one launcher run folder independently of the launcher (D-ABR-024).

  python -I -B tools/verify_run.py <run folder> [--out <result.json>]

Nothing the launcher concluded is trusted. From the sealed folder alone, with Python's own hashlib and the official
0.33 judges of the audited tree work-0.33 (imported read-only, never modified):
  seal       every file listed in RUN_SHA256SUMS.json re-hashes to its digest, and no other file is present;
  identity   the staged kernel, Limine EFI and the variable-store template digest are the pinned ones; the staged
             limine.conf is exactly the harness template with hashlib's BLAKE2b-512 of the staged kernel; the
             selected kernel is the one evidence/campaign-033/BUILD_MANIFEST.json names;
  command    the QEMU command is exactly abr_boot_001.qemu_command(...) + ["-S"] (the harness's own function);
  official   the harness conditions on the run's single boot:
               production  C0, C1, C2, C3, C4, C5, C9, C10, C11, C12, C13 (abr_boot_001.judge, profile 0.33);
               launchpad   C0-C5, C9-C11, and tools/g033/launch_probe.py judge_lines(..., "launchpad");
               early-fail  the fault probe's `early` rules (tools/g6/fault_probe.py), applied to the log;
             C6 (restart) and C7 (series) do not apply to one launch; C8 is the seal check above;
  shutdown   QEMU exited 0 after a QMP quit (SHUTDOWN reason host-qmp-quit) and the job held no process after;
  agreement  the launcher's live verdicts agree with the official ones (boot, services, launcher contract).
0.33.1 (F-VML-01): a production run whose kernel reported a DEGRADED clock (a host pause, a TSC anomaly) is judged by
the official rules made for it: C0-C4, C9, C10 and C13 as usual; C5 without its continuity part, plus a check that
every heartbeat gap is one the kernel reported itself with its forward TSC jump; and launch_probe `degraded-clock` in
place of C11 and C12, which assume an uninterrupted clock. A launchpad run with a DEGRADED clock has no official
judge; 0.33.2 (D-ABR-026 3B) judges it with tools/judge_launchpad_degraded.py, a COMPOSITE of launch_probe's own
`launchpad` and `degraded-clock` rule sets (named composite_ in the checks, never official_).
0.33.2: a run ending CLOCK_ANOMALY_CAUSE_NOT_ESTABLISHED booted and was stopped on request like an OK run, so it is
judged the same way.
The official conditions and the agreement apply to a run that ended OK (a full boot and a requested shutdown) and to
the early-fail build. For any other result (a killed QEMU, the time limit) they are recorded under "information" and
not counted: the campaign checks that run's own designed outcome.
Exit 0 only if every applicable check holds. Standard library only. Writes only --out, if given.
"""
import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

VML = Path(__file__).resolve().parents[1]
HOME = VML.parent
W = HOME / "work-0.33"
sys.path.insert(0, str(W / "tools"))
sys.path.insert(0, str(W / "tools" / "g033"))
import abr_boot_001 as h  # noqa: E402
import launch_probe as lp  # noqa: E402

PINNED = {"QEMU_EXE": "47d57a6072e0bb3bd98f87926eb129eb1736dfe818c67b3b81ef7ce4edd0b3cd",
          "LIMINE_EFI": "e486ae7abd7d5b88f98f43cfd6e8f9057ff975ecd667dfb33f1581de36e00982",
          "FW_CODE": "33090cc07675baa5190d9f1e84bf5176b33bcbfa9bacac522961150cdb6dbb2a",
          "FW_VARS": "5d2ac383371b408398accee7ec27c8c09ea5b74a0de0ceea6513388b15be5d1e",
          "LIMINE_CONF": "ea81dbc99c3b4621d69fc852d58a9cb35c125f0b24a4aa73bc094c2a1d05d3b9"}
# The service part of launch_probe.judge_lines (its common checks from the 0.32b service probe, in its order).
SERVICE_KEYS = ["every_service_line_known_grammar", "status_rounds_complete", "reasons_appendix_a_or_none",
                "compromise_none_known_everywhere", "diag_codes_registered", "heartbeats_present",
                "readiness_counts_possible", "probe_claims_consistent", "overrun_claims_over_the_budget",
                "service_event_times_non_decreasing", "status_lines_consistent_with_transitions_mapping_and_clock",
                "counter_available_and_increasing_every_round", "static_entries_unavailable_not_installed"]
def gaps_explained(lines):
    """Every heartbeat discontinuity must be one the kernel reported (HEARTBEAT_GAP from the previous to the next
    heartbeat, with the right skip) after its TSC_FORWARD_JUMP, since the previous heartbeat (F-VML-01)."""
    prev, jump, gap, bad, seen = None, False, None, [], []
    for l in lines:
        if l.startswith("ABR|CLOCK|anomaly=TSC_FORWARD_JUMP|"):
            jump = True
        elif l.startswith("ABR|CLOCK|anomaly=HEARTBEAT_GAP|"):
            f = dict(p.split("=", 1) for p in l[len("ABR|CLOCK|"):].split("|"))
            gap = (int(f["from_s"]), int(f["to_s"]), int(f["skipped"]))
        elif l.startswith("ABR|TICK|uptime_s="):
            n = int(l[len("ABR|TICK|uptime_s="):].split("|")[0])
            if prev is not None and n != prev + 1:
                if gap == (prev, n, n - prev - 1) and jump:
                    seen.append(gap)
                else:
                    bad.append((prev, n))
            elif gap is not None:
                bad.append(("reported but not shown", gap))
            prev, jump, gap = n, False, None
    return not bad, seen, bad


MANIFEST_KEY = {"production": "default", "launchpad": "launchpad", "early-fail": "early"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--out")
    a = ap.parse_args()
    run = Path(a.run).resolve()
    rec = json.loads((run / "launch.json").read_text())
    c, info = {}, {"run": str(run), "run_id": rec.get("run_id"), "result_recorded": rec.get("result")}

    # seal
    sums = json.loads((run / "RUN_SHA256SUMS.json").read_text())
    present = {p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file()} - {"RUN_SHA256SUMS.json"}
    c["seal_every_digest_matches"] = all(sha(run / k) == v for k, v in sums.items())
    c["seal_covers_every_file"] = present == set(sums)
    info["sealed_files"] = len(sums)

    started = rec.get("verdicts", {}).get("kernel_boot") != "NOT STARTED"
    key = rec.get("selected_kernel", {}).get("key")
    manifest = json.loads((W / "evidence" / "campaign-033" / "BUILD_MANIFEST.json").read_text())["kernels"]
    pin = manifest[MANIFEST_KEY[key]]["sha256"] if key in MANIFEST_KEY else None
    if "selected_kernel" in rec:
        c["selected_kernel_is_the_campaign_build"] = rec["selected_kernel"].get("expected_sha256") == pin
    else:
        info["selected_kernel"] = "not recorded: refused before a kernel was examined (duplicate launch)"
    if not started:
        info["note"] = "refused before start: only the seal and the refusal record are checked"
        c["refused_qemu_never_started"] = "qemu_command" not in rec and not (run / "serial.log").exists()
        return finish(a, c, info)

    esp = run / "esp"
    kernel = (esp / "boot" / "abraham-kernel").read_bytes()
    template = (W / "boot" / "limine.conf").read_text(encoding="ascii")
    c["staged_kernel_is_the_pinned_kernel"] = hashlib.sha256(kernel).hexdigest() == pin
    c["staged_limine_efi_pinned"] = sha(esp / "EFI" / "BOOT" / "BOOTX64.EFI") == PINNED["LIMINE_EFI"]
    c["limine_conf_template_pinned"] = sha(W / "boot" / "limine.conf") == PINNED["LIMINE_CONF"]
    want_conf = template.replace("{KERNEL_BLAKE2B}", hashlib.blake2b(kernel).hexdigest())
    c["staged_limine_conf_is_the_harness_template_with_hashlib_blake2b"] = \
        (esp / "boot" / "limine" / "limine.conf").read_bytes() == want_conf.encode("ascii")
    c["vars_template_digest_at_staging_pinned"] = rec.get("staged", {}).get("vars.fd") == PINNED["FW_VARS"]
    inputs = {i["name"]: i for i in rec.get("inputs", [])}
    c["recorded_qemu_exe_digest_pinned"] = inputs.get("QEMU executable", {}).get("sha256") == PINNED["QEMU_EXE"]
    c["recorded_firmware_digest_pinned"] = inputs.get("UEFI firmware code (edk2)", {}).get("sha256") == PINNED["FW_CODE"]

    # command: the harness's own function
    cmd = rec["qemu_command"]
    qemu_dir = Path(cmd[0]).parent
    h.use_qemu(qemu_dir)
    port = int(re.search(r"tcp:127\.0\.0\.1:(\d+),", " ".join(cmd)).group(1))
    accel = rec["accelerator"]
    want = h.qemu_command(accel, "host" if accel == "whpx" else "max", run, esp, port, run / "serial.log") + ["-S"]
    c["qemu_command_is_the_harness_command"] = [str(x) for x in want] == cmd
    if not c["qemu_command_is_the_harness_command"]:
        info["command_difference"] = [(x, y) for x, y in zip(want, cmd) if str(x) != y]

    # official judges on this single boot
    opt = rec.get("timer_throttling_opt_out", {})
    host = {"restart_mode": "single launch (no restart)", "qmp_events": rec.get("qmp_events", []),
            "status_after_window_1": rec.get("status_before_quit") or {},
            "timer_throttling_opt_out_enabled": True,
            "timer_throttling_opt_out_boot1": {k: opt.get(k) for k in ("ok", "error", "control_mask", "state_mask")},
            "qemu_command": cmd, "timeline": rec.get("timeline", [])}
    args = argparse.Namespace(run_id=rec["run_id"], stable_seconds=15, profile="0.33", expect_memtest=False)
    lines = h.serial_lines(run / "serial.log")
    live = rec.get("verdicts", {})
    applicable = rec.get("result") in ("OK", "CLOCK_ANOMALY_CAUSE_NOT_ESTABLISHED") or key == "early-fail"
    # 0.33.1: a run that booted and was shut down on request, but whose services or contract the launcher found
    # wrong, is judged too; there only the agreement with the official judges counts.
    agreement_only = rec.get("result") in ("SERVICES_NOT_AS_DESIGNED", "LAUNCHER_CONTRACT_INCONSISTENT")
    counted = c
    if not applicable:
        c = {}  # collected below, then moved to information
    degraded = any(l.startswith("ABR|CLOCK|state=DEGRADED") for l in lines)
    info["clock_degraded_by_the_kernel"] = degraded
    if key in ("production", "launchpad"):
        res = h.judge(run / "serial.log", copy.deepcopy(host), args)
        conds = res["conditions"]
        names = ["C0_configuration", "C1_loader", "C2_kernel_entered", "C3_operational", "C4_banner", "C5_no_crash",
                 "C9_memory_ownership", "C10_lifecycle_events", "C11_clock"]
        if degraded:
            names = ["C0_configuration", "C1_loader", "C2_kernel_entered", "C3_operational", "C4_banner",
                     "C9_memory_ownership", "C10_lifecycle_events"]
            c5 = conds["C5_no_crash"]
            c["official_C5_parts_no_fault_no_guest_reset_still_running"] = (
                not c5.get("faults") and not c5.get("guest_resets") and (c5.get("status") or {}).get("status") == "running")
            ok_gaps, seen, bad = gaps_explained(lines)
            c["every_heartbeat_gap_reported_by_the_kernel_with_its_tsc_jump"] = ok_gaps
            info["kernel_reported_pauses"] = seen
            info["unexplained_gaps"] = bad
            info["not_applicable_after_a_degraded_clock"] = {
                "C5_no_crash (its continuity part)": c5.get("pass"), "C11_clock": conds["C11_clock"].get("boot1", {}).get("pass"),
                "C12_services": None}
        # C9-C12 judge boot 1 and boot 2; one launch has no boot 2, so its (empty) half is not applicable.
        for n in names:
            v = conds[n]
            ok = v.get("boot1", v).get("pass") if n in ("C9_memory_ownership", "C10_lifecycle_events", "C11_clock") else v.get("pass")
            c[f"official_{n}"] = ok is True
        b1 = h.split_boots(lines)[0]
        s1 = h.judge_services(b1, "0.32b")
        if key == "production" and degraded:
            dc, di = lp.judge_lines(lines, "degraded-clock")
            c["official_launch_probe_degraded_clock"] = all(dc.values())
            info["degraded_clock_failed"] = [k for k, v in dc.items() if not v]
            info["not_applicable_after_a_degraded_clock"]["C12_services"] = s1["pass"]
            a1 = h.judge_launcher(b1)
            c["official_C13_launcher_boot1"] = a1["pass"] is True
            info["c13_items_failed"] = [k for k, v in a1["items"].items() if not v]
            official_contract = c["official_C13_launcher_boot1"] and c["official_launch_probe_degraded_clock"]
            official_services = all(dc.get(k) is True for k in SERVICE_KEYS if k in dc)
            c["degraded_clock_service_keys_present"] = sum(1 for k in SERVICE_KEYS if k in dc) == len(SERVICE_KEYS) - 1
        elif key == "launchpad" and degraded:
            sys.path.insert(0, str(VML / "tools"))
            import judge_launchpad_degraded as jld  # noqa: E402
            cc, ci = jld.judge_lines(lines)
            c["composite_launchpad_degraded_clock"] = all(cc.values())
            info["composite_failed"] = [k for k, v in cc.items() if not v]
            info["composite_judge"] = "tools/judge_launchpad_degraded.py (launch_probe launchpad + degraded-clock rules; COMPOSITE, not official)"
            info["not_applicable_after_a_degraded_clock"]["C12_services"] = s1["pass"]
            official_contract = c["composite_launchpad_degraded_clock"]
            official_services = all(cc.get(k) is True for k in SERVICE_KEYS if k in cc)
        elif key == "production":
            c["official_C12_services_boot1"] = s1["pass"] is True
            a1 = h.judge_launcher(b1)
            c["official_C13_launcher_boot1"] = a1["pass"] is True
            info["c13_items_failed"] = [k for k, v in a1["items"].items() if not v]
            official_contract = c["official_C13_launcher_boot1"]
            official_services = c["official_C12_services_boot1"]
        else:
            lc, li = lp.judge_lines(lines, "launchpad")
            c["official_launch_probe_launchpad"] = all(lc.values())
            info["launch_probe_failed"] = [k for k, v in lc.items() if not v]
            official_contract = c["official_launch_probe_launchpad"]
            c["launch_probe_service_keys_present"] = all(k in lc for k in SERVICE_KEYS)
            official_services = all(lc.get(k) is True for k in SERVICE_KEYS)
        info["official_failed"] = sorted(k for k, v in conds.items() if v.get("pass") is False)
        info["not_applicable"] = ["C6_restart (one launch, no restart)", "C7_reproducible (a series)",
                                  "C8_evidence (replaced by the seal check)"]
        no_judge = False
        official_boot = all(c[f"official_{n}"] for n in names[1:6]) if not degraded else (
            all(c[f"official_{n}"] for n in names[1:5]) and c["official_C5_parts_no_fault_no_guest_reset_still_running"]
            and c["every_heartbeat_gap_reported_by_the_kernel_with_its_tsc_jump"])
        if not no_judge:
            c["agreement_kernel_boot"] = (live.get("kernel_boot") == "PASS") == official_boot
            c["agreement_services"] = (live.get("services") == "AS DESIGNED") == official_services
            c["agreement_launcher_contract"] = (live.get("launcher_contract") == "CONSISTENT") == official_contract
            c["official_boot_pass"] = official_boot
            c["official_contract_pass"] = official_contract
    elif key == "early-fail":
        faults = [l for l in lines if l.startswith("ABR|FAULT|")]
        f = dict(p.split("=", 1) for p in faults[0][len("ABR|FAULT|"):].split("|")) if faults else {}
        after = lines[lines.index(faults[0]) + 1:] if faults else []
        regs = rec.get("registers_before_quit") or ""
        rip = re.search(r"RIP=([0-9a-f]+)", regs)
        hlt = re.search(r"HLT=(\d)", regs)
        sys.path.insert(0, str(W / "tools" / "g6"))
        import fault_probe as fp  # noqa: E402
        halted = (hlt and hlt.group(1) == "1") or (rip is not None and fp.byte_before(kernel, int(rip.group(1), 16)) == 0xF4)
        failed_init = [l for l in after if l.startswith("ABR|INIT|") and "|to=FAILED|" in l]
        # The fault probe's `early` rules (tools/g6/fault_probe.py), applied to this log.
        c.update({
            "early_exactly_one_fault_report": len(faults) == 1,
            "early_reason_timer_unavailable": f.get("reason") == "TIMER_UNAVAILABLE",
            "early_detail_injected": f.get("detail") == "DIAG_INJECTED_EARLY_INIT_FAILURE",
            "early_init_state_cpu_tables_loaded": f.get("init_state") == "CPU_TABLES_LOADED",
            "early_uptime_none": f.get("uptime_ms") == "NONE",
            "early_one_failed_transition": len(failed_init) == 1 and "|from=CPU_TABLES_LOADED|" in failed_init[0]
                                           and failed_init[0].endswith("|reason=TIMER_UNAVAILABLE"),
            "early_no_banner": not any(l.startswith("ABR|BANNER") for l in lines),
            "early_never_operational": h.OPERATIONAL not in lines,
            "early_no_heartbeat_after_fault": not any(l.startswith("ABR|TICK") for l in after),
            "early_no_guest_reset": not any(e.get("event") == "RESET" for e in rec.get("qmp_events", [])),
            "early_qemu_running_before_quit": (rec.get("status_before_quit") or {}).get("status") == "running",
            "early_cpu_stopped_in_halt": bool(halted),
            "early_kernel_entered": h.ENTRY in lines,
        })
        info["rip"], info["hlt"] = rip and rip.group(1), hlt and hlt.group(1)
        c["agreement_kernel_boot"] = live.get("kernel_boot") == "FAILED AS DESIGNED"
        c["agreement_launcher_contract"] = live.get("launcher_contract") == "NOT REACHED"

    if not applicable:
        info["official_for_information_only"] = c
        info["why_not_counted"] = f"result {rec.get('result')}: no full boot with a requested shutdown"
        if agreement_only:
            info["why_not_counted"] = f"result {rec.get('result')}: only the agreement with the official judges counts"
            for k, v in c.items():
                if k.startswith("agreement_"):
                    counted[k] = v
        c = counted
    sh = rec.get("shutdown", {})
    qlog = run / "qmp.jsonl"  # absent when QEMU died before its QMP channel answered
    events = [json.loads(l) for l in qlog.read_text().splitlines() if l.strip()] if qlog.is_file() else []
    info["qmp_log_present"] = qlog.is_file()
    quit_seen = any(e["kind"] == "event" and e["message"].get("event") == "SHUTDOWN"
                    and e["message"].get("data", {}).get("reason") == "host-qmp-quit" for e in events)
    info["shutdown"] = sh
    if rec.get("result") == "VM_TERMINATED_UNEXPECTEDLY":
        c["unexpected_exit_recorded_and_no_qemu_left"] = sh.get("mode") == "QEMU_EXITED_UNEXPECTEDLY" \
            and sh.get("job_active_processes_after") == 0 and not sh.get("pinned_qemu_processes_after")
    else:
        c["shutdown_clean_qmp_quit_exit_0"] = sh.get("mode") == "CLEAN_QMP_QUIT" and sh.get("qemu_exit_code") == 0 and quit_seen
        c["no_qemu_process_left"] = sh.get("job_active_processes_after") == 0 and not sh.get("pinned_qemu_processes_after")
    return finish(a, c, info)


def finish(a, c, info):
    result = {"verdict": "VERIFIED" if all(c.values()) else "NOT VERIFIED", "checks": c, **info,
              "verifier": str(Path(__file__).resolve()), "verifier_sha256": sha(Path(__file__).resolve()),
              "judge_sha256": sha(W / "tools" / "abr_boot_001.py"),
              "launch_probe_sha256": sha(W / "tools" / "g033" / "launch_probe.py")}
    text = json.dumps(result, indent=1, sort_keys=True) + "\n"
    if a.out:
        Path(a.out).write_text(text)
    print(json.dumps({"run": info.get("run_id"), "verdict": result["verdict"],
                      "failed": [k for k, v in c.items() if not v]}))
    return 0 if result["verdict"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
