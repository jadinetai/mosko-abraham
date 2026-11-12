"""G6/G7 fault probe: boot a diagnostic fault build and judge its failure report (scored).

  python -I tools/g6/fault_probe.py --run-id G6-F001 --qemu-dir <dir> --accel whpx --cpu host
         --kernel build/diag/abraham-kernel-diag-fault-ud.elf --expect ud --limine-efi <EFI>

--expect ud     #UD before OPERATIONAL: FAULT vector=6 name=INVALID_OPCODE, rip within 16 bytes of
                the ABR|DIAG expect_rip; OPERATIONAL never printed
--expect pf     #PF after OPERATIONAL: FAULT vector=14 name=PAGE_FAULT, cr2 = ABR|DIAG expect_cr2,
                error code bit 1 (write) set and bit 0 (present) clear; no heartbeat after the fault
--expect early  controlled early-init failure: FAULT reason=TIMER_UNAVAILABLE detail=DIAG_INJECTED...;
                no banner, no OPERATIONAL
All: no guest RESET (no triple fault), QEMU still running, CPU halted (HLT=1) after the fault.
Uses the harness's QEMU command, staging and timer opt-out (paused start). Evidence: evidence/g6/.

0.31a additions (work-0.31 only):
--expect-kernel-sha256 is required; any other kernel is refused before anything runs.
--expect collision-check   F-029-01 negative control (diag-legacy-collision): the live ownership
                check reports PT_FRAME_FREE for page-table frames that lie in a USABLE map entry, then
                FAULT reason=FRAME_OWNERSHIP_COLLISION source=MEMCHECK; no banner, never OPERATIONAL
--expect collision-alloc   D-ABR-012 (diag-legacy-collision + diag-memcheck-nonfatal + diag-mem-exhaust):
                the allocation guard refuses a live page-table frame: FAULT reason=FRAME_OWNERSHIP_COLLISION
                source=ALLOCATOR naming a frame the earlier (report-only) check listed; the serious-violation
                line shows the frame quarantined (not free, not in pool), allocator FAULTED, a further
                allocation refused, and the APIC mapping still intact; never OPERATIONAL
--expect double-release    D-ABR-012 (diag-double-release): FAULT reason=FRAME_DOUBLE_RELEASE
                source=ALLOCATOR for the injected frame; free_frames unchanged by the second release and
                equal to the free bitmap, the frame free exactly once, allocator FAULTED, a further
                allocation refused; never OPERATIONAL

0.31b additions (work-0.31b only):
--expect init-skip   lifecycle (diag-init-skip): `ABR|INIT|refused|from=MEMORY_OWNED|to=OPERATIONAL`, then
                FAULT reason=INIT_INVALID_TRANSITION; no ownership check, no banner, never OPERATIONAL
Every expectation also checks the 0.31b fault report: the FAULT line's init_state is the lifecycle state the
fault must happen in, uptime_ms is NONE exactly when the clock had not started, one INIT transition to FAILED
from that state with the fault's code as reason, and a context dump of 1..8 ABR|FAULTCTX events (consecutive
seq) whose last record is this FAULT with the same code, closed by ABR|FAULT_END|events_dumped=<count>.
"""

# Where each injected fault must be reported (0.31b lifecycle), and whether the clock was running.
EXPECTED_STATE = {"ud": ("OWNERSHIP_VERIFIED", True), "pf": ("OPERATIONAL", True), "early": ("CPU_TABLES_LOADED", False),
                  "collision-check": ("TIMER_RUNNING", True), "collision-alloc": ("TIMER_RUNNING", True),
                  "double-release": ("OWNERSHIP_VERIFIED", True), "init-skip": ("MEMORY_OWNED", False)}

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

FAULT = re.compile(r"^ABR\|FAULT\|(?P<body>.*)$")


def byte_before(elf, vaddr):
    """Byte at vaddr-1 in the ELF's loaded image (via program headers), or None."""
    import struct
    phoff, = struct.unpack_from("<Q", elf, 0x20)
    phentsize, phnum = struct.unpack_from("<HH", elf, 0x36)
    target = vaddr - 1
    for i in range(phnum):
        ptype, _, off, va, _, filesz, _, _ = struct.unpack_from("<IIQQQQQQ", elf, phoff + i * phentsize)
        if ptype == 1 and va <= target < va + filesz:
            return elf[off + target - va]
    return None


def fields(body):
    return dict(part.split("=", 1) for part in body.split("|") if "=" in part)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--qemu-dir", required=True)
    p.add_argument("--accel", choices=("whpx", "tcg"), required=True)
    p.add_argument("--cpu", required=True)
    p.add_argument("--kernel", required=True)
    p.add_argument("--limine-efi", required=True)
    p.add_argument("--expect", choices=("ud", "pf", "early", "collision-check", "collision-alloc", "double-release",
                                        "init-skip"), required=True)
    p.add_argument("--expect-kernel-sha256", required=True)
    p.add_argument("--wait", type=int, default=90)
    args = p.parse_args()

    h.use_qemu(args.qemu_dir)
    actual = hashlib.sha256(Path(args.kernel).read_bytes()).hexdigest()
    if actual != args.expect_kernel_sha256.lower():
        print(f"REFUSED: kernel {args.kernel} has SHA-256 {actual}, expected {args.expect_kernel_sha256}; nothing was run")
        return 2
    run = h.EVIDENCE / "g6" / args.run_id
    if run.exists():
        raise SystemExit(f"REFUSED: {run} exists")
    esp = run / "esp"
    (esp / "EFI" / "BOOT").mkdir(parents=True)
    (esp / "boot" / "limine").mkdir(parents=True)
    kernel = Path(args.kernel).read_bytes()
    shutil.copyfile(args.limine_efi, esp / "EFI" / "BOOT" / "BOOTX64.EFI")
    (esp / "boot" / "abraham-kernel").write_bytes(kernel)
    conf = h.LIMINE_CONF.read_text(encoding="ascii").replace("{KERNEL_BLAKE2B}", hashlib.blake2b(kernel).hexdigest())
    (esp / "boot" / "limine" / "limine.conf").write_text(conf, encoding="ascii", newline="\n")
    shutil.copyfile(h.FW_VARS, run / "vars.fd")
    serial = run / "serial.log"
    port = h.free_port()
    command = h.qemu_command(args.accel, args.cpu, run, esp, port, serial) + ["-S"]
    meta = {"run_id": args.run_id, "label": "VM_MEASURED, deliberate-fault diagnostic build (never accepted)",
            "expect": args.expect, "accelerator": args.accel, "cpu_model": args.cpu,
            "qemu": h.first_line([str(h.QEMU), "--version"]), "qemu_executable_sha256": h.sha256(h.QEMU),
            "kernel": str(Path(args.kernel)), "kernel_sha256": hashlib.sha256(kernel).hexdigest(),
            "limine_efi_sha256": h.sha256(args.limine_efi), "qemu_command": command, "started_utc": h.utc()}
    t0 = time.monotonic()
    with open(run / "qemu-stderr.txt", "wb") as err:
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err)
        meta["timer_throttling_opt_out"] = h.opt_out_timer_throttling(proc.pid)
        qmp = h.Qmp(port, run / "qmp.jsonl", t0)
        qmp.command("cont")
        got = h.wait_for(lambda: any(FAULT.match(l) for l in h.serial_lines(serial)), args.wait)
        meta["fault_seen_after_s"] = round(time.monotonic() - t0, 2) if got else None
        time.sleep(5)  # anything printed after the fault would appear here
        meta["status"] = qmp.command("query-status").get("return")
        meta["registers"] = qmp.command("human-monitor-command", **{"command-line": "info registers"}).get("return")
        qmp.command("quit")
        meta["qemu_exit"] = proc.wait(timeout=20)
    meta["qmp_events"] = qmp.events

    lines = h.serial_lines(serial)
    faults = [(i, fields(m["body"])) for i, l in enumerate(lines) for m in [FAULT.match(l)] if m]
    diag = next((fields(l[len("ABR|DIAG|"):]) for l in lines if l.startswith("ABR|DIAG|")), {})
    first_fault = faults[0][0] if faults else None
    after = lines[first_fault + 1:] if faults else []
    regs = meta["registers"] or ""
    hlt = (re.search(r"HLT=(\d)", regs) or [None, None])[1]
    rip = (re.search(r"RIP=([0-9a-f]+)", regs) or [None, None])[1]
    f = faults[0][1] if faults else {}
    checks = {
        "exactly_one_fault_report": len(faults) == 1,
        "no_operational_after_fault": not any(l == h.OPERATIONAL for l in after),
        "no_heartbeat_after_fault": not any(l.startswith("ABR|TICK") for l in after),
        "no_guest_reset": not any(e.get("event") == "RESET" for e in meta["qmp_events"]),
        "qemu_running": (meta["status"] or {}).get("status") == "running",
        # QEMU reports HLT=1 under TCG; under WHPX the hypervisor runs hlt itself and QEMU shows 0.
        # Independent check: the instruction just before RIP in the loaded image is HLT (0xF4).
        "cpu_stopped_in_halt": hlt == "1" or (rip is not None and byte_before(kernel, int(rip, 16)) == 0xF4),
        "kernel_entered": h.ENTRY in lines,
    }
    if args.expect == "ud":
        expect_rip = int(diag.get("expect_rip", "0"), 16)
        got_rip = int(f.get("rip", "0"), 16)
        checks.update({"vector_6": f.get("vector") == "6", "name_invalid_opcode": f.get("name") == "INVALID_OPCODE",
                       "rip_at_injection_site": 0 <= got_rip - expect_rip < 16,
                       "never_operational": h.OPERATIONAL not in lines})
    elif args.expect == "pf":
        err_code = int(f.get("error", "0"), 16)
        checks.update({"vector_14": f.get("vector") == "14", "name_page_fault": f.get("name") == "PAGE_FAULT",
                       "cr2_equals_target": f.get("cr2") == diag.get("expect_cr2"),
                       "error_write_bit_set": bool(err_code & 0x2), "error_not_present": not (err_code & 0x1),
                       "was_operational_before": h.OPERATIONAL in lines[:first_fault] if faults else False})
    elif args.expect == "early":
        checks.update({"reason_timer_unavailable": f.get("reason") == "TIMER_UNAVAILABLE",
                       "detail_injected": f.get("detail") == "DIAG_INJECTED_EARLY_INIT_FAILURE",
                       "no_banner": not any(l.startswith("ABR|BANNER") for l in lines),
                       "never_operational": h.OPERATIONAL not in lines})
    else:
        # 0.31a memory-ownership negative controls
        usable = []
        for l in lines:
            if l.startswith("ABR|MEMMAP|"):
                m = fields(l[len("ABR|MEMMAP|"):])
                if m.get("type") == "USABLE":
                    usable.append((int(m["base"], 16), int(m["base"], 16) + int(m["length"], 16)))
        in_usable = lambda a: any(b <= a < e for b, e in usable)
        violations = [fields(l[len("ABR|MEMCHECK|"):]) for l in lines if l.startswith("ABR|MEMCHECK|") and "|violation=" in l]
        free_pt = [int(v["frame"], 16) for v in violations if v.get("violation") == "PT_FRAME_FREE"]
        serious = {}
        for l in lines:
            if l.startswith("ABR|MEM|serious|"):
                serious.update(fields(l[len("ABR|MEM|serious|"):]))
        common = {"never_operational": h.OPERATIONAL not in lines,
                  "no_banner": not any(l.startswith("ABR|BANNER") for l in lines),
                  "allocator_was_ready": any(l.startswith("ABR|MEM|state=READY|") for l in lines)}
        if args.expect == "collision-check":
            checks.update(common)
            checks.update({"reason_collision": f.get("reason") == "FRAME_OWNERSHIP_COLLISION",
                           "source_memcheck": f.get("source") == "MEMCHECK",
                           "stage_timer": f.get("stage") == "timer",
                           "init_check_passed_first": any(l.startswith("ABR|MEMCHECK|stage=init|") and l.endswith("result=PASS")
                                                          for l in lines),
                           "free_page_tables_reported": len(free_pt) >= 1,
                           "reported_frames_inside_usable": bool(free_pt) and all(in_usable(a) for a in free_pt)})
        elif args.expect == "init-skip":
            checks.update(common)
            checks.update({"reason_invalid_transition": f.get("reason") == "INIT_INVALID_TRANSITION",
                           "from_memory_owned_to_operational": f.get("from") == "MEMORY_OWNED" and f.get("to") == "OPERATIONAL",
                           "refusal_line_printed": "ABR|INIT|refused|from=MEMORY_OWNED|to=OPERATIONAL" in lines,
                           "injection_announced": any(l.startswith("ABR|DIAG|injecting=init_skip|") for l in lines),
                           "advance_never_returned": not any("init_skip_returned" in l for l in lines),
                           "no_ownership_check_after": not any(l.startswith("ABR|MEMCHECK|") for l in lines)})
        elif args.expect == "collision-alloc":
            frame = int(f.get("frame", "0x0"), 16)
            checks.update(common)
            checks.update({"reason_collision": f.get("reason") == "FRAME_OWNERSHIP_COLLISION",
                           "source_allocator": f.get("source") == "ALLOCATOR",
                           "report_only_check_saw_it_first": frame in free_pt,
                           "frame_inside_usable": in_usable(frame),
                           "frame_quarantined": serious.get("frame_free") == "false" and serious.get("frame_in_pool") == "false"
                                                and serious.get("quarantined") == "1",
                           "allocator_faulted": serious.get("state") == "FAULTED",
                           "next_alloc_refused": serious.get("alloc_after") == "FRAME_ALLOCATOR_FAULTED",
                           "apic_mapping_intact": serious.get("apic_mapping_intact") == "true",
                           "free_count_consistent": serious.get("free_frames") == serious.get("free_bitmap")})
        else:  # double-release
            frame = int(f.get("frame", "0x0"), 16)
            checks.update(common)
            checks.update({"reason_double_release": f.get("reason") == "FRAME_DOUBLE_RELEASE",
                           "source_allocator": f.get("source") == "ALLOCATOR",
                           "frame_is_injected_frame": f.get("frame") == diag.get("frame") and frame != 0,
                           "first_release_ok": diag.get("first_release_ok") == "true",
                           "free_pool_unchanged": serious.get("free_frames") == diag.get("free_frames_before")
                                                  and serious.get("free_bitmap") == diag.get("free_frames_before"),
                           "frame_free_exactly_once": serious.get("frame_free") == "true",
                           "allocator_faulted": serious.get("state") == "FAULTED",
                           "next_alloc_refused": serious.get("alloc_after") == "FRAME_ALLOCATOR_FAULTED",
                           "never_returned_to_caller": not any("double_release_returned" in l for l in lines)})
    # 0.31b fault report: lifecycle state, uptime truthfulness, FAILED transition, event context.
    want_state, clock_running = EXPECTED_STATE[args.expect]
    code = f.get("reason") or f.get("name")
    failed_init = [fields(l[len("ABR|INIT|"):]) for l in after if l.startswith("ABR|INIT|") and "|to=FAILED|" in l]
    ctx = [fields(l[len("ABR|FAULTCTX|"):]) for l in after if l.startswith("ABR|FAULTCTX|")]
    end = [fields(l[len("ABR|FAULT_END|"):]) for l in after if l.startswith("ABR|FAULT_END|")]
    seqs = [int(c.get("seq", "-1")) for c in ctx]
    checks.update({
        "fault_init_state": f.get("init_state") == want_state,
        "fault_uptime_truthful": (f.get("uptime_ms", "").isdigit() if clock_running else f.get("uptime_ms") == "NONE"),
        "one_failed_transition": len(failed_init) == 1 and failed_init[0].get("from") == want_state
                                 and failed_init[0].get("reason") == code,
        "context_dumped_1_to_8": 1 <= len(ctx) <= 8 and len(end) == 1 and end[0].get("events_dumped") == str(len(ctx)),
        "context_seq_consecutive": bool(seqs) and seqs == list(range(seqs[0], seqs[0] + len(seqs))),
        "context_ends_with_this_fault": bool(ctx) and ctx[-1].get("kind") == "FAULT" and ctx[-1].get("code") == code,
        "no_nested_fault": not any(l.startswith("ABR|FAULT|nested") for l in lines),
    })
    result = {"verdict": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
              "fault_report": f, "diag_line": diag, "rip_after": rip, "hlt_after": hlt,
              "not_claimed": "fault handling of this one injected case only"}
    (run / "probe.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    (run / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    h.seal(run)
    print(json.dumps({"run": args.run_id, "verdict": result["verdict"], "failed_checks":
                      [k for k, v in checks.items() if not v], "fault": f, "rip_after": rip, "hlt": hlt}))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
