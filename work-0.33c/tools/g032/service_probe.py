"""ABRAHAM 0.32 service probe: DIAGNOSTIC service builds that must keep the kernel running, judged on their output.

  python -I -B tools/g032/service_probe.py run --run-id <id> --qemu-dir <dir> --accel whpx|tcg --kernel <elf>
         --expect-kernel-sha256 <sha> --limine-efi <EFI> --expect <mode> [--seconds N]
  python -I -B tools/g032/service_probe.py judge --serial <serial.log> --expect <mode> --out <dir> [--grammar 0.32|0.32b]
         (judges an existing sealed serial log again; writes only <dir>. S16 uses it for the diag-tsc runs; 0.32b uses
         it to show audit finding 3 in the preserved 0.32 evidence)

0.32b (D-ABR-020):
  - expectations follow the corrected contract. The probe step is judged like every step, so in svc-slow the probe
    is overrun 1 of 3 (probe_timing=OVERRUN), the service fails after 2 loop steps, and it is never shown AVAILABLE;
  - new mode svc-cascade (finding 1);
  - the common checks are hardened like C12 (finding 4): readiness counts possible (1 unit, the budget of every
    entry here); probe and overrun duration claims consistent with the budget and the probe_timing verdict; service
    event times non-decreasing; every status line consistent with the entry's transitions, the status mapping and
    the ABR|CLOCK lines.
  --grammar 0.32 judges a 0.32 log (no probe_timing field); the default is 0.32b.

Modes (design §7; expected outcomes fixed here, before any run):
  svc-cycle     (diag-svc-cycle, S19) registry=REFUSED with SVC_DEPENDENCY_CYCLE at svc.netmon, no transition at all,
                every entry UNAVAILABLE (dev.net0 NOT_INSTALLED, the others NONE), liveness UNKNOWN, heartbeats continue.
  svc-refusals  (diag-svc-refusals, S07/S17/S18) a start before OPERATIONAL refused (SVC_KERNEL_NOT_OPERATIONAL) and
                nothing else of the manager before OPERATIONAL; then a normal start; queries: unknown name and a near
                miss TARGET_UNKNOWN, start CAP_MISSING, an unknown operation OPERATION_UNKNOWN, status OK/AVAILABLE; an
                invalid transition RUNNING->STARTING refused with SVC_INVALID_TRANSITION, state unchanged; the counter
                stays RUNNING/AVAILABLE and keeps counting.
  svc-defects   (diag-svc-defects, S08/S09) svc.diagready FAILED by its own readiness check (SVC_DIAG_NOT_READY), svc.diagliar
                FAILED as contradicted (SVC_READINESS_CONTRADICTED), neither ever RUNNING, both UNAVAILABLE/LOST;
                svc.diagdep withheld by svc.diagready (FAILED), UNAVAILABLE, reason NONE; the counter unaffected.
  svc-slow      (diag-svc-slow, S11; corrected in 0.32b) svc.diagslow RUNNING after readiness with probe_timing=OVERRUN
                (the probe, at least 15,000 us, is overrun 1); then 2 loop overruns (consecutive 2, 3), DEGRADED once,
                FAILED with SVC_STEP_OVERRUN after 2 loop steps (steps=2, overruns=3), never shown AVAILABLE; the
                counter AVAILABLE and increasing; no clock anomaly; heartbeats consecutive.
  svc-stall     (diag-svc-stall, S12, informational) svc.diagstall overruns 3 times by about 6 s and FAILS; the clock
                guard reports TSC_FORWARD_JUMP and DEGRADED (the misattribution limit); from the first clock anomaly on,
                no status is AVAILABLE; the counter keeps counting.
  svc-cascade   (diag-svc-cascade, 0.32b audit finding 1) svc.diagflaky RUNNING, then FAILED on its 3rd loop step
                (SVC_DIAG_INJECTED_STEP_ERROR) after 2 good steps; svc.diagdep2, which depends on it, is STOPPING
                (SVC_DEPENDENCY_LOST) then STOPPED, and was NEVER stepped after its dependency left RUNNING: its
                steps and value equal svc.diagflaky's good steps and value (2 and 3) in every later round; the
                counter is unaffected.
  tsc-backward / tsc-jump  (judge only, S16) before the injected clock anomaly svc.counter is AVAILABLE/LIVE; every
                status round after it shows svc.counter UNKNOWN / OBSERVATION_STALE / liveness UNKNOWN with clock=DEGRADED,
                while its value still increases; dev.net0 and svc.netmon stay UNAVAILABLE / NOT_INSTALLED.
Common: kernel entered, OPERATIONAL, no ABR|FAULT, every service line in a known grammar, every reason an Appendix A
code (parsed from the baseline) or NONE, compromise NONE_KNOWN on every status line, every diag= code registered. A
status round cut by the end of capture is tolerated only at the very end (as in C12). Uses the harness's QEMU command,
staging and verified timer opt-out. Evidence: evidence/g032/<run-id>/, sealed.
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

PROD = ["dev.net0", "svc.counter", "svc.netmon"]
TABLES = {"svc-cycle": PROD + ["svc.diagcyc"], "svc-refusals": PROD,
          "svc-defects": PROD + ["svc.diagready", "svc.diagliar", "svc.diagdep"],
          "svc-slow": PROD + ["svc.diagslow"], "svc-stall": PROD + ["svc.diagstall"],
          "svc-cascade": PROD + ["svc.diagflaky", "svc.diagdep2"],
          "tsc-backward": PROD, "tsc-jump": PROD}
START_REFUSED = re.compile(r"^ABR\|SVC\|start=REFUSED\|diag=(?P<diag>[A-Z_]+)\|init_state=(?P<st>[A-Z_]+)$")
REG_REFUSED = re.compile(r"^ABR\|SVC\|registry=REFUSED\|diag=(?P<diag>[A-Z_]+)\|entry=(?P<entry>\d+)$")
READY_FAIL = re.compile(r"^ABR\|SVC\|id=(?P<id>[a-z0-9.]+)\|ready=FAIL\|diag=(?P<diag>[A-Z0-9_]+)$")
REFUSED_T = re.compile(r"^ABR\|SVC\|id=(?P<id>[a-z0-9.]+)\|refused\|from=(?P<frm>[A-Z]+)\|to=(?P<to>[A-Z]+)\|diag=(?P<diag>[A-Z_]+)$")
OVERRUN = re.compile(r"^ABR\|SVC\|id=(?P<id>[a-z0-9.]+)\|overrun\|elapsed_us=(?P<us>\d+)\|budget_us=1000\|consecutive=(?P<n>\d+)"
                     r"\|diag=SVC_STEP_OVERRUN$")
CHANGE = re.compile(r"^ABR\|SVC\|id=(?P<id>[a-z0-9.]+)\|status_change=(?P<what>DEGRADED\|diag=SVC_STEP_OVERRUN|RECOVERED)$")
UNMEASURED = re.compile(r"^ABR\|SVC\|id=(?P<id>[a-z0-9.]+)\|unmeasured\|diag=SVC_STEP_UNMEASURED$")
QUERY = re.compile(r"^ABR\|SVCQUERY\|op=(?P<op>[A-Za-z]+)\|target=(?P<target>[A-Za-z0-9.]+)\|result=(?P<result>OK|REFUSED)"
                   r"(?:\|status=(?P<status>[A-Z]+))?\|reason=(?P<reason>[A-Z_]+)$")
GRAMMARS = h.SVC_GRAMMARS + (START_REFUSED, REG_REFUSED, READY_FAIL, REFUSED_T, OVERRUN, CHANGE, UNMEASURED, QUERY)


def fields(body):
    return dict(part.split("=", 1) for part in body.split("|") if "=" in part)


def rounds_of(lines, table):
    """Status rounds (one line per entry, in table order, contiguous). A round cut by the end of capture is dropped
    and reported; any other incomplete round makes `complete` False."""
    svc = [(i, l) for i, l in enumerate(lines) if l.startswith("ABR|SVC")]
    last_abr = max((i for i, l in enumerate(lines) if l.startswith("ABR|")), default=-1)
    cut = None
    if svc and svc[-1][0] == last_abr and svc[-1][1].startswith("ABR|SVCSTATUS|") and not h.SVC_STATUS.match(svc[-1][1]):
        cut = svc.pop()
    status = [(i, m.groupdict()) for i, l in svc for m in [h.SVC_STATUS.match(l)] if m]
    rounds, complete, partial = [], True, 0
    for k in range(0, len(status), len(table)):
        g = status[k:k + len(table)]
        ids, idx = [d["id"] for _, d in g], [i for i, _ in g]
        contiguous = idx == list(range(idx[0], idx[0] + len(idx)))
        if ids == table and contiguous:
            rounds.append({d["id"]: dict(d, line=i) for i, d in g})
            continue
        last_svc = max(i for i, _ in svc)
        if k + len(table) >= len(status) and contiguous and ids == table[:len(ids)] and idx[-1] == last_svc \
                and (idx[-1] == last_abr or cut is not None):
            partial = len(g)
        else:
            complete = False
        break
    return rounds, complete, {"cut_line": cut[1] if cut else None, "partial_final_round_lines": partial}, \
        [l for i, l in svc if (cut is None or i != cut[0])]


BUDGET = 1  # every entry these modes start declares 1 work unit
INSTALLED = {"dev.net0": False}


def common_checks(lines, table, grammar="0.32b"):
    public = h.appendix_a_codes()
    registered = h.registered_codes()
    rounds, complete, end, svc = rounds_of(lines, table)
    stray = [l for l in svc if not any(g.match(l) for g in GRAMMARS)]
    st = [m.groupdict() for l in svc for m in [h.SVC_STATUS.match(l)] if m]
    reasons = [d["reason"] for d in st] + [m["reason"] for l in svc for m in [QUERY.match(l)] if m]
    diags = [m.group(1) for l in svc for m in re.finditer(r"\|diag=([A-Z0-9_]+)", l)]
    ticks = [fields(l[len("ABR|TICK|"):]) for l in lines if l.startswith("ABR|TICK|")]
    readies = [m.groupdict() for l in svc for m in [h.SVC_READY.match(l)] if m]
    overruns = [m.groupdict() for l in svc for m in [OVERRUN.match(l)] if m]
    ev_ups = [m["uptime"] for l in svc for m in [h.SVC_EVENT.match(l)] if m]

    def probe_claim_ok(d):
        us = int(d["us"]) if d["us"].isdigit() else None
        if grammar == "0.32":
            return d["timing"] is None
        want = "UNMEASURED" if us is None else ("OVERRUN" if us > h.STEP_BUDGET_US else "IN_BUDGET")
        return d["timing"] == want

    checks = {
        "kernel_entered": h.ENTRY in lines,
        "operational": h.OPERATIONAL in lines,
        "no_fault": not any(l.startswith("ABR|FAULT") for l in lines),
        "every_service_line_known_grammar": bool(svc) and not stray,
        "status_rounds_complete": complete and len(rounds) >= 2,
        "reasons_appendix_a_or_none": len(public) == 27 and bool(reasons) and all(r == "NONE" or r in public for r in reasons),
        "compromise_none_known_everywhere": bool(st) and all(d["compromise"] == "NONE_KNOWN" for d in st),
        "diag_codes_registered": all(c in registered for c in diags),
        "heartbeats_present": len(ticks) >= 5,
        # 0.32b (finding 4)
        "readiness_counts_possible": all(d["pu"].isdigit() and 1 <= int(d["pu"]) <= BUDGET and d["pu"] == d["ku"] == d["obs"]
                                         for d in readies),
        "probe_claims_consistent": all(probe_claim_ok(d) for d in readies),
        "overrun_claims_over_the_budget": all(int(o["us"]) > h.STEP_BUDGET_US for o in overruns),
        "service_event_times_non_decreasing": all(u.isdigit() for u in ev_ups) and [int(u) for u in ev_ups] == sorted(int(u) for u in ev_ups),
        "status_lines_consistent_with_transitions_mapping_and_clock": not h.status_contradictions(lines, INSTALLED),
    }
    return checks, {"rounds": rounds, "end_of_capture": end, "stray": stray[:8], "svc": svc, "ticks": ticks}


def tr(svc, name):
    return [(m["seq"], m["frm"], m["to"], m["diag"]) for l in svc for m in [h.SVC_TRANSITION.match(l)] if m and m["id"] == name]


def increasing(rounds, name="svc.counter"):
    v = [int(r[name]["value"]) for r in rounds if r[name]["value"].isdigit()]
    return len(v) == len(rounds) >= 2 and all(b > a for a, b in zip(v, v[1:]))


def counter_running_ok(svc):
    return tr(svc, "svc.counter") == [("1", "DECLARED", "STARTING", None), ("2", "STARTING", "RUNNING", None)]


def status_is(d, *want):
    keys = ("state", "status", "reason", "liveness")
    return tuple(d[k] for k in keys[:len(want)]) == want


def judge_lines(lines, expect, grammar="0.32b"):
    table = TABLES[expect]
    checks, x = common_checks(lines, table, grammar)
    rounds, svc = x["rounds"], x["svc"]
    op = lines.index(h.OPERATIONAL) if h.OPERATIONAL in lines else len(lines)
    secs = [int(t["uptime_s"]) for t in x["ticks"]]
    checks["heartbeat_seconds_consecutive"] = expect in ("svc-stall", "tsc-jump") or (
        bool(secs) and secs == list(range(secs[0], secs[0] + len(secs))))
    if expect == "svc-cycle":
        rr = [m.groupdict() for l in svc for m in [REG_REFUSED.match(l)] if m]
        checks.update({
            "registry_refused_for_the_cycle": rr == [{"diag": "SVC_DEPENDENCY_CYCLE", "entry": "2"}],
            "no_transition_at_all": not any(h.SVC_TRANSITION.match(l) for l in svc),
            "no_registry_ok": not any(h.SVC_REGISTRY.match(l) for l in svc),
            "dev_net0_not_installed": all(status_is(r["dev.net0"], "DECLARED", "UNAVAILABLE", "NOT_INSTALLED", "UNKNOWN") for r in rounds),
            "others_unavailable_no_reason": all(status_is(r[n], "DECLARED", "UNAVAILABLE", "NONE", "UNKNOWN")
                                                and r[n]["steps"] == "0" for r in rounds for n in table[1:]),
            "event_dump_has_only_the_refusal": [(e["code"], e["arg"]) for l in svc for e in [h.SVC_EVENT.match(l)] if e]
                                               == [("SVC_REGISTRY_REFUSED", "0x2")],
        })
    elif expect == "svc-refusals":
        early = [(i, m.groupdict()) for i, l in enumerate(lines) for m in [START_REFUSED.match(l)] if m]
        q = [(m["op"], m["target"], m["result"], m["status"], m["reason"]) for l in svc for m in [QUERY.match(l)] if m]
        ref = [m.groupdict() for l in svc for m in [REFUSED_T.match(l)] if m]
        before_op = [l for l in lines[:op] if l.startswith("ABR|SVC")]
        checks.update({
            "early_start_refused_before_operational": len(early) == 1 and early[0][0] < op
                                                      and early[0][1] == {"diag": "SVC_KERNEL_NOT_OPERATIONAL", "st": "OWNERSHIP_VERIFIED"},
            "only_that_refusal_before_operational": len(before_op) == 1,
            "normal_start_afterwards": counter_running_ok(svc) and sum(1 for l in svc if h.SVC_REGISTRY.match(l)) == 1,
            "queries_answered_exactly": q == [("status", "svc.undeclared", "REFUSED", None, "TARGET_UNKNOWN"),
                                              ("status", "SVC.COUNTER", "REFUSED", None, "TARGET_UNKNOWN"),
                                              ("start", "svc.counter", "REFUSED", None, "CAP_MISSING"),
                                              ("reboot", "svc.counter", "REFUSED", None, "OPERATION_UNKNOWN"),
                                              ("status", "svc.counter", "OK", "AVAILABLE", "NONE")],
            "invalid_transition_refused": ref == [{"id": "svc.counter", "frm": "RUNNING", "to": "STARTING", "diag": "SVC_INVALID_TRANSITION"}],
            "counter_unchanged_and_counting": all(status_is(r["svc.counter"], "RUNNING", "AVAILABLE", "NONE", "LIVE") for r in rounds)
                                              and increasing(rounds),
        })
    elif expect == "svc-defects":
        rf = [(m["id"], m["diag"]) for l in svc for m in [READY_FAIL.match(l)] if m]
        wh = [(m["id"], m["dep"], m["st"]) for l in svc for m in [h.SVC_WITHHELD.match(l)] if m]
        checks.update({
            "counter_running": counter_running_ok(svc),
            "diagready_failed_by_its_own_check": tr(svc, "svc.diagready") == [("1", "DECLARED", "STARTING", None),
                                                                               ("2", "STARTING", "FAILED", "SVC_READINESS_FAILED")],
            "diagliar_contradicted": tr(svc, "svc.diagliar") == [("1", "DECLARED", "STARTING", None),
                                                                 ("2", "STARTING", "FAILED", "SVC_READINESS_CONTRADICTED")],
            "readiness_failures_reported": rf == [("svc.diagready", "SVC_DIAG_NOT_READY"), ("svc.diagliar", "SVC_READINESS_CONTRADICTED")],
            "neither_ever_running": not any(t[2] == "RUNNING" for n in ("svc.diagready", "svc.diagliar") for t in tr(svc, n)),
            "dependent_withheld": wh == [("svc.netmon", "dev.net0", "DECLARED"), ("svc.diagdep", "svc.diagready", "FAILED")]
                                  and not tr(svc, "svc.diagdep"),
            "failed_ones_unavailable_lost": all(status_is(r[n], "FAILED", "UNAVAILABLE", "NONE", "LOST") for r in rounds
                                                for n in ("svc.diagready", "svc.diagliar")),
            "dependent_unavailable_no_reason": all(status_is(r["svc.diagdep"], "DECLARED", "UNAVAILABLE", "NONE", "UNKNOWN") for r in rounds),
            "counter_unaffected": all(status_is(r["svc.counter"], "RUNNING", "AVAILABLE", "NONE", "LIVE") for r in rounds)
                                  and increasing(rounds),
        })
    elif expect in ("svc-slow", "svc-stall"):
        name = "svc.diagslow" if expect == "svc-slow" else "svc.diagstall"
        ov = [m.groupdict() for l in svc for m in [OVERRUN.match(l)] if m and m["id"] == name]
        ch = [m["what"] for l in svc for m in [CHANGE.match(l)] if m and m["id"] == name]
        last = rounds[-1][name] if rounds else {}
        anom = [i for i, l in enumerate(lines) if l.startswith("ABR|CLOCK|anomaly=")]
        after_anom = [m.groupdict() for i, l in enumerate(lines) if anom and i > anom[0] for m in [h.SVC_STATUS.match(l)] if m]
        floor_us = 15_000 if expect == "svc-slow" else 5_000_000
        # 0.32b (finding 3): the slow service's probe is its first overrun, so it fails after 2 loop steps; the stall
        # service's probe does not stall, so it still fails after 3 loop steps.
        loop_steps = "2" if expect == "svc-slow" else "3"
        own = [m.groupdict() for l in svc for m in [h.SVC_STATUS.match(l)] if m and m["id"] == name]
        rd = [m.groupdict() for l in svc for m in [h.SVC_READY.match(l)] if m and m["id"] == name]
        checks.update({
            "counter_running": counter_running_ok(svc),
            "running_after_readiness": tr(svc, name)[:2] == [("1", "DECLARED", "STARTING", None), ("2", "STARTING", "RUNNING", None)],
            "exactly_three_overruns": [o["n"] for o in ov] == ["1", "2", "3"] and all(int(o["us"]) >= floor_us for o in ov),
            "degraded_once": ch == ["DEGRADED|diag=SVC_STEP_OVERRUN"],
            "failed_after_the_third": tr(svc, name)[2:] == [("3", "RUNNING", "FAILED", "SVC_STEP_OVERRUN")],
            "never_stepped_again": bool(last) and (last["state"], last["status"], last["liveness"], last["steps"], last["overruns"])
                                   == ("FAILED", "UNAVAILABLE", "LOST", loop_steps, "3"),
            "counter_keeps_counting": increasing(rounds),
        })
        if expect == "svc-slow":
            checks.update({
                "no_clock_anomaly": not any(l.startswith("ABR|CLOCK|") for l in lines),
                "counter_unaffected": all(status_is(r["svc.counter"], "RUNNING", "AVAILABLE", "NONE", "LIVE") for r in rounds),
                "probe_overrun_stated_with_readiness": len(rd) == 1 and rd[0]["us"].isdigit() and int(rd[0]["us"]) >= floor_us
                                                       and (grammar == "0.32" or rd[0]["timing"] == "OVERRUN"),
                "never_available_after_a_probe_overrun": bool(own) and all(d["status"] != "AVAILABLE" for d in own),
            })
        else:
            deg = [fields(l[len("ABR|CLOCK|"):]) for l in lines if l.startswith("ABR|CLOCK|state=DEGRADED")]
            checks.update({
                "stall_seen_as_tsc_jump": any("anomaly=TSC_FORWARD_JUMP" in l for l in lines),
                "clock_degraded_once_for_the_jump": len(deg) == 1 and deg[0].get("reason") == "TSC_FORWARD_JUMP",
                "nothing_available_after_the_anomaly": bool(after_anom) and all(d["status"] != "AVAILABLE" for d in after_anom),
                "counter_unknown_stale_after": all(d["status"] == "UNKNOWN" and d["reason"] == "OBSERVATION_STALE"
                                                   for d in after_anom if d["id"] == "svc.counter"),
            })
    elif expect == "svc-cascade":
        fl, dp = tr(svc, "svc.diagflaky"), tr(svc, "svc.diagdep2")
        stop_line = next((i for i, l in enumerate(lines) if l.startswith("ABR|SVC|id=svc.diagdep2|") and "|to=STOPPED" in l), None)
        after = [r for r in rounds if stop_line is not None and r["svc.diagdep2"]["line"] > stop_line]
        checks.update({
            "counter_running": counter_running_ok(svc),
            "dependency_failed_on_its_third_step": fl == [("1", "DECLARED", "STARTING", None), ("2", "STARTING", "RUNNING", None),
                                                         ("3", "RUNNING", "FAILED", "SVC_DIAG_INJECTED_STEP_ERROR")],
            "dependent_stopped_not_failed": dp == [("1", "DECLARED", "STARTING", None), ("2", "STARTING", "RUNNING", None),
                                                   ("3", "RUNNING", "STOPPING", "SVC_DEPENDENCY_LOST"), ("4", "STOPPING", "STOPPED", None)],
            "dependent_never_stepped_after_its_dependency_failed": bool(after) and all(
                (r["svc.diagdep2"]["steps"], r["svc.diagdep2"]["value"]) == (r["svc.diagflaky"]["steps"], r["svc.diagflaky"]["value"])
                == ("2", "3") for r in after),
            "states_after_the_stop": bool(after) and all(
                status_is(r["svc.diagdep2"], "STOPPED", "UNAVAILABLE", "NONE", "UNKNOWN")
                and status_is(r["svc.diagflaky"], "FAILED", "UNAVAILABLE", "NONE", "LOST") for r in after),
            "counter_unaffected": all(status_is(r["svc.counter"], "RUNNING", "AVAILABLE", "NONE", "LIVE") for r in rounds)
                                  and increasing(rounds),
        })
    else:  # tsc-backward / tsc-jump (S16)
        anom = next((i for i, l in enumerate(lines) if l.startswith("ABR|CLOCK|anomaly=")), None)
        before = [r for r in rounds if anom is not None and r["svc.counter"]["line"] < anom]
        after = [r for r in rounds if anom is not None and r["svc.counter"]["line"] > anom]
        checks.update({
            "clock_anomaly_seen": anom is not None,
            "counter_available_before": bool(before) and all(status_is(r["svc.counter"], "RUNNING", "AVAILABLE", "NONE", "LIVE")
                                                             and r["svc.counter"]["clock"] == "OK" for r in before),
            "counter_unknown_after_on_every_round": len(after) >= 1 and all(
                status_is(r["svc.counter"], "RUNNING", "UNKNOWN", "OBSERVATION_STALE", "UNKNOWN") and r["svc.counter"]["clock"] == "DEGRADED"
                for r in after),
            "counter_value_still_increases": increasing(rounds),
            "static_facts_unchanged": all(status_is(r[n], "DECLARED", "UNAVAILABLE", "NOT_INSTALLED", "UNKNOWN") for r in rounds
                                          for n in ("dev.net0", "svc.netmon")),
            "clock_field_follows_the_guard": all(r[n]["clock"] == "DEGRADED" for r in after for n in PROD),
        })
    return checks, {"rounds": len(rounds), "end_of_capture": x["end_of_capture"], "stray": x["stray"],
                    "counter_values": [r["svc.counter"]["value"] for r in rounds]}


def run_vm(args):
    h.use_qemu(args.qemu_dir)
    kernel = Path(args.kernel).read_bytes()
    if hashlib.sha256(kernel).hexdigest() != args.expect_kernel_sha256.lower():
        print(f"REFUSED: kernel {args.kernel} has SHA-256 {hashlib.sha256(kernel).hexdigest()}, "
              f"expected {args.expect_kernel_sha256}; nothing was run")
        return 2
    run = h.EVIDENCE / "g032" / args.run_id
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
    meta = {"run_id": args.run_id, "label": "VM_MEASURED, DIAGNOSTIC service build (never accepted)",
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
    checks, info = judge_lines(lines, args.expect)
    opt = meta["timer_throttling_opt_out"]
    checks["timer_opt_out_verified"] = isinstance(opt, dict) and opt.get("ok") is True
    checks["still_running_at_the_end"] = (meta.get("status") or {}).get("status") == "running"
    checks["no_guest_reset"] = not any(e.get("event") == "RESET" for e in qmp.events)
    result = {"verdict": "PASS" if all(checks.values()) else "FAIL", "checks": checks, **info,
              "evidence_label": "VM_MEASURED", "not_claimed": "behavior of this one DIAGNOSTIC build on this VM only"}
    meta["ended_utc"] = h.utc()
    (run / "probe.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    (run / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    h.seal(run)
    print(json.dumps({"run": args.run_id, "verdict": result["verdict"], "failed_checks": [k for k, v in checks.items() if not v],
                      "rounds": info["rounds"], "end_of_capture": info["end_of_capture"], "stray": info["stray"]}))
    return 0 if result["verdict"] == "PASS" else 1


def judge_existing(args):
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    serial = Path(args.serial)
    lines = h.serial_lines(serial)
    checks, info = judge_lines(lines, args.expect, args.grammar)
    out.mkdir(parents=True)
    result = {"verdict": "PASS" if all(checks.values()) else "FAIL", "checks": checks, **info, "grammar": args.grammar,
              "source_serial": str(serial), "source_serial_sha256": h.sha256(serial),
              "evidence_label": "VM_MEASURED (judged again from a sealed run)",
              "not_claimed": "anything beyond the service part of this one run"}
    (out / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    h.seal(out)
    print(json.dumps({"verdict": result["verdict"], "failed_checks": [k for k, v in checks.items() if not v], **info}))
    return 0 if result["verdict"] == "PASS" else 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("run")
    r.add_argument("--run-id", required=True)
    r.add_argument("--qemu-dir", required=True)
    r.add_argument("--accel", choices=("whpx", "tcg"), required=True)
    r.add_argument("--kernel", required=True)
    r.add_argument("--expect-kernel-sha256", required=True)
    r.add_argument("--limine-efi", required=True)
    r.add_argument("--expect", choices=("svc-cycle", "svc-refusals", "svc-defects", "svc-slow", "svc-stall", "svc-cascade"), required=True)
    r.add_argument("--seconds", type=int, default=12)
    j = sub.add_parser("judge")
    j.add_argument("--serial", required=True)
    j.add_argument("--expect", choices=tuple(TABLES), required=True)
    j.add_argument("--out", required=True)
    j.add_argument("--grammar", choices=("0.32", "0.32b"), default="0.32b")
    a = p.parse_args()
    return run_vm(a) if a.mode == "run" else judge_existing(a)


if __name__ == "__main__":
    raise SystemExit(main())
