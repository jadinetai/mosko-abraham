"""ABRAHAM 0.33 launch probe: DIAGNOSTIC launcher builds, judged on their serial output (design §9, §11).

  python -I -B tools/g033/launch_probe.py run --run-id <id> --qemu-dir <dir> --accel whpx|tcg --kernel <elf>
         --expect-kernel-sha256 <sha> --limine-efi <EFI> --expect <mode> [--seconds N]
  python -I -B tools/g033/launch_probe.py judge --serial <serial.log> --expect <mode> --out <dir>

Modes (expected outcomes fixed here, from the design, before any run):
  launchpad        (diag-launchpad) the 17 script rows exactly as design §9: every fact, state, stage, Appendix A
                   reason and diagnostic code; the transitions of each request right before its result; the routed
                   `start svc.counter` answered CAP_MISSING by the unchanged 0.32b contract; the discovery answer
                   (APPQUERY + APPINFO) agreeing with the latest status round; the summary counts equal to the lines;
                   the injected RUNNING transition refused (LAUNCH_INVALID_TRANSITION) with the state unchanged.
  degraded-clock   (judge only: the tsc-backward / tsc-jump observation runs) the production launcher lines, with
                   APPINFO following every status round; after the clock anomaly app.counterview's prerequisites are
                   UNSATISFIED with svc.counter:UNKNOWN:OBSERVATION_STALE (never satisfied on stale data, Q3), and before
                   it they were SATISFIED; no launch line, no execution claim.
  app-registry-dup / app-false-exec / app-unknown-req
                   (diag-app-*) the application table refused at boot with exactly APP_DUPLICATE_ID entry 2,
                   APP_EXEC_CLAIM_UNSUPPORTED entry 1, APP_UNKNOWN_REQUIREMENT entry 1; no APPINFO and no launch line;
                   the services exactly as in production.
Common to every mode, and independent of the exact table (so falsified logs are caught by rules, not only by
comparison): the service checks of the 0.32b service probe (production table); every launch-result fact rule (a
REFUSED request was never validated and stopped at an early gate; a NOT_EXECUTED one was validated, is known and
stopped at AUTHORIZATION; facts after the deciding gate are NOT_EVALUATED; a presented capability is NO_AUTHORITY /
AUTHZ_UNAVAILABLE; the reason belongs to the diagnostic code; executed=NO, process=NONE, result=NOT_EXECUTED); no
line anywhere claims execution; launch lines only after OPERATIONAL, the APP registry and the first status round;
APPINFO with every status round, consistent with it; every reason an Appendix A code; every diag= code registered.
Evidence: evidence/g033/<run-id>/, sealed. Uses the harness's QEMU command, staging and verified timer opt-out.
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

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "g032"))
import abr_boot_001 as h  # noqa: E402
import service_probe as sp  # noqa: E402

PROD = h.SVC_TABLE
FIELDS = ["req", "op", "target", "class", "admission", "structure", "known", "prerequisites", "unavailable", "support",
          "capability", "authorization", "executed", "process", "state", "stage", "result", "verification", "boundary",
          "reason", "diag"]
TRANS = re.compile(r"^ABR\|LAUNCH\|req=(?P<req>\d+)\|seq=(?P<seq>\d+)\|from=(?P<frm>[A-Z_]+)\|to=(?P<to>[A-Z_]+)$")
ROUTED = re.compile(r"^ABR\|LAUNCH\|req=(?P<req>\d+)\|routed=SERVICE\|op=(?P<op>[a-z]+)\|target=(?P<target>[a-z0-9.]+)$")
REFUSED_T = re.compile(r"^ABR\|LAUNCH\|req=(?P<req>\d+)\|refused\|from=(?P<frm>[A-Z_]+)\|to=(?P<to>[A-Z_]+)\|diag=(?P<diag>[A-Z_]+)$")
STATE_L = re.compile(r"^ABR\|LAUNCH\|req=(?P<req>\d+)\|state=(?P<state>[A-Z_]+)$")
QUERY = re.compile(r"^ABR\|APPQUERY\|req=(?P<req>\d+)\|op=(?P<op>status|list)\|target=(?P<target>app[a-z0-9.]*)\|result=OK$")
SUMMARY = re.compile(r"^ABR\|LAUNCHPAD\|requests=(?P<requests>\d+)\|refused=(?P<refused>\d+)\|not_executed=(?P<ne>\d+)"
                     r"\|discovery=(?P<disc>\d+)\|routed_to_services=(?P<routed>\d+)\|executed=(?P<executed>\d+)"
                     r"\|processes=(?P<processes>\d+)\|executor=(?P<executor>[A-Z_]+)$")
INJECT = re.compile(r"^ABR\|DIAG\|injecting=launch_invalid_transition\|req=(?P<req>\d+)\|to=(?P<to>[A-Z_]+)$")
DIAG_REASON = {"LAUNCH_ID_NOT_INCREASING": "REQUEST_REPLAYED", "LAUNCH_OPERATION_UNKNOWN": "OPERATION_UNKNOWN",
               "LAUNCH_TARGET_UNKNOWN": "TARGET_UNKNOWN", "LAUNCH_REGISTRY_REFUSED": "TARGET_UNKNOWN",
               "LAUNCH_CAP_MISSING": "CAP_MISSING", "LAUNCH_NO_AUTHORITY": "AUTHZ_UNAVAILABLE"}
EARLY = ("ADMISSION", "STRUCTURE", "OPERATION", "RECOGNITION")


def parse_result(l):
    """A LAUNCHRESULT line as an ordered field dict, or None if it is not exactly the grammar's field sequence."""
    if not l.startswith("ABR|LAUNCHRESULT|"):
        return None
    parts = l[len("ABR|LAUNCHRESULT|"):].split("|")
    if not all("=" in p for p in parts):
        return None
    kv = [p.split("=", 1) for p in parts]
    keys = [k for k, _ in kv]
    want = FIELDS[:3] + (["target_len"] if "target_len" in keys else []) + FIELDS[3:]
    if keys != want:
        return None
    d = dict(kv)
    if not d["req"].isdigit() or (d["target"] == "MALFORMED") != ("target_len" in d):
        return None
    return d


def expected_script():
    """design §9, rows 1-17, written before any run. Each row: (req, kind, overrides)."""
    val = {"admission": "FRESH", "structure": "WELL_FORMED", "known": "YES", "support": "NONE", "capability": "NONE",
           "executed": "NO", "process": "NONE", "state": "NOT_EXECUTED", "stage": "AUTHORIZATION",
           "result": "NOT_EXECUTED", "verification": "NOT_APPLICABLE", "boundary": "COOPERATIVE", "class": "MUTATE",
           "op": "start", "prerequisites": "SATISFIED", "unavailable": "NONE", "authorization": "CAP_MISSING",
           "reason": "CAP_MISSING", "diag": "LAUNCH_CAP_MISSING"}
    ref = {"admission": "FRESH", "structure": "WELL_FORMED", "known": "NO", "prerequisites": "NOT_EVALUATED",
           "unavailable": "NOT_EVALUATED", "support": "NOT_EVALUATED", "capability": "NONE",
           "authorization": "NOT_EVALUATED", "executed": "NO", "process": "NONE", "state": "REFUSED",
           "result": "NOT_EXECUTED", "verification": "NOT_APPLICABLE", "boundary": "COOPERATIVE", "op": "start",
           "class": "MUTATE", "stage": "RECOGNITION", "reason": "TARGET_UNKNOWN", "diag": "LAUNCH_TARGET_UNKNOWN"}
    net = {"prerequisites": "UNSATISFIED", "unavailable": "svc.netmon:UNAVAILABLE:NOT_INSTALLED"}
    parse = {"op": "NONE", "target": "NONE", "class": "NONE", "structure": "MALFORMED", "known": "NOT_EVALUATED",
             "stage": "STRUCTURE", "reason": "PARSE_ERROR"}
    return [
        ("1", "result", dict(val, target="app.counterview")),
        ("2", "result", dict(val, target="app.netstatus", **net)),
        ("3", "result", dict(val, target="app.browser", **net)),
        ("4", "result", dict(val, target="app.counterview", capability="PRESENTED", authorization="NO_AUTHORITY",
                             reason="AUTHZ_UNAVAILABLE", diag="LAUNCH_NO_AUTHORITY")),
        ("5", "result", dict(val, op="stop", target="app.counterview")),
        ("6", "result", dict(val, op="inspect", target="app.counterview", **{"class": "INSPECT_PROTECTED"})),
        ("7", "query", {"op": "status", "target": "app.counterview"}),
        ("8", "result", dict(ref, target="app.nosuch")),
        ("9", "result", dict(ref, target="app.counterviews")),
        ("10", "result", {**ref, **parse, "target": "MALFORMED", "target_len": "15", "diag": "LAUNCH_PARSE_TARGET_MALFORMED"}),
        ("11", "result", {**ref, **parse, "target": "MALFORMED", "target_len": "5", "diag": "LAUNCH_PARSE_TARGET_MALFORMED"}),
        ("12", "result", dict(ref, op="UNKNOWN", target="NONE", known="NOT_EVALUATED", stage="OPERATION",
                              reason="OPERATION_UNKNOWN", diag="LAUNCH_OPERATION_UNKNOWN", **{"class": "NONE"})),
        ("13", "result", dict(ref, **parse, diag="LAUNCH_PARSE_PARAMETER")),
        ("14", "result", dict(ref, **parse, diag="LAUNCH_PARSE_SPACING")),
        ("15", "result", dict(ref, **parse, diag="LAUNCH_PARSE_TOO_LONG")),
        ("1", "result", dict(ref, op="NONE", target="NONE", admission="NOT_INCREASING", structure="NOT_EVALUATED",
                             known="NOT_EVALUATED", stage="ADMISSION", reason="REQUEST_REPLAYED",
                             diag="LAUNCH_ID_NOT_INCREASING", **{"class": "NONE"})),
        ("16", "routed", {"op": "start", "target": "svc.counter"}),
    ]


def fact_rules_ok(d, public):
    """Rules every launch result must obey, whatever the request was."""
    s = d["state"]
    early_ok = s == "REFUSED" and d["stage"] in EARLY
    late_ok = s == "NOT_EXECUTED" and d["stage"] == "AUTHORIZATION" and d["known"] == "YES" and d["structure"] == "WELL_FORMED" \
        and d["admission"] == "FRESH" and d["class"] in ("MUTATE", "INSPECT_PROTECTED") \
        and d["authorization"] == ("NO_AUTHORITY" if d["capability"] == "PRESENTED" else "CAP_MISSING")
    unknown_ok = d["known"] == "YES" or (d["prerequisites"] == d["unavailable"] == d["support"] == "NOT_EVALUATED"
                                        and d["authorization"] == "NOT_EVALUATED")
    pre_ok = (d["prerequisites"] == "SATISFIED") == (d["unavailable"] == "NONE") \
        and (d["prerequisites"] == "NOT_EVALUATED") == (d["unavailable"] == "NOT_EVALUATED")
    reason_ok = d["reason"] in public and (d["diag"] not in DIAG_REASON or DIAG_REASON[d["diag"]] == d["reason"]) \
        and (not d["diag"].startswith("LAUNCH_PARSE_") or d["reason"] == "PARSE_ERROR")
    stage_reason_ok = {"ADMISSION": "REQUEST_REPLAYED", "STRUCTURE": "PARSE_ERROR", "OPERATION": "OPERATION_UNKNOWN",
                       "RECOGNITION": "TARGET_UNKNOWN"}.get(d["stage"], d["reason"]) == d["reason"]
    fixed_ok = (d["executed"], d["process"], d["result"], d["verification"], d["boundary"]) == \
        ("NO", "NONE", "NOT_EXECUTED", "NOT_APPLICABLE", "COOPERATIVE")
    # the admission gate decides exactly the out-of-order ids, and an out-of-order request is not even parsed
    admission_ok = (d["stage"] == "ADMISSION") == (d["admission"] == "NOT_INCREASING") \
        and (d["admission"] == "FRESH" or d["structure"] == "NOT_EVALUATED")
    # a refused request was never validated, so nothing after its deciding gate was evaluated
    gate_order_ok = d["stage"] not in ("ADMISSION", "STRUCTURE", "OPERATION") or d["known"] == "NOT_EVALUATED"
    return (early_ok or late_ok) and unknown_ok and pre_ok and reason_ok and stage_reason_ok and fixed_ok \
        and admission_ok and gate_order_ok


def launch_checks(lines, expect):
    public = h.appendix_a_codes()
    registered = h.registered_codes()
    op = lines.index(h.OPERATIONAL) if h.OPERATIONAL in lines else None
    abr = [(i, l) for i, l in enumerate(lines) if l.startswith("ABR|")]
    regs_ok = [(i, m.groupdict()) for i, l in abr for m in [h.APP_REG_OK.match(l)] if m]
    regs_ref = [(i, m.groupdict()) for i, l in abr for m in [h.APP_REG_REFUSED.match(l)] if m]
    first_status = next((i for i, l in abr if h.SVC_STATUS.match(l)), None)
    svc_reg = next((i for i, l in abr if h.SVC_REGISTRY.match(l)), None)
    rounds, used, partial = h.launcher_rounds(lines)
    launch_lines = [(i, l) for i, l in abr if l.startswith(h.LAUNCH_PREFIXES) or INJECT.match(l)]
    infos = [(i, m.groupdict()) for i, l in abr for m in [h.APPINFO.match(l)] if m]
    last_abr = abr[-1][0] if abr else -1
    cut = abr[-1][1] if abr and abr[-1][1].startswith("ABR|APP") and not (h.APPINFO.match(abr[-1][1]) or h.APP_REG_OK.match(abr[-1][1])) else None
    diags = [m.group(1) for _, l in abr if l.startswith(("ABR|APP", "ABR|LAUNCH")) for m in re.finditer(r"\|diag=([A-Z0-9_]+)", l)]
    # supplement fix (ABR-0.33-L003..L006, J005): with a refused registry no round may carry APPINFO at all;
    # the rule below demanded an APPINFO group after every round, which applies only to a valid registry
    registry_valid = len(regs_ok) == 1 and not regs_ref
    c = {
        "no_execution_claimed": not h.execution_claims(lines),
        "launcher_diag_codes_registered": bool(registered) and all(x in registered for x in diags),
        "appinfo_rounds_consistent": (not registry_valid and all(not g for _, g, _ in rounds)) or registry_valid and all(ok for _, _, ok in rounds) and all(
            (d["pre"], d["un"]) == h.appinfo_expected(r, dict((a[0], a[4]) for a in h.APP_TABLE)[d["id"]].split(","))
            and d["at"] == r["dev.net0"][1]["at"] for r, g, _ in rounds for _, d in g),
        "nothing_before_operational": op is not None and all(i > op for i, l in abr if l.startswith(("ABR|APP", "ABR|LAUNCH"))),
    }
    info = {"launch_lines": len(launch_lines), "appinfo_rounds": len(rounds), "end_of_capture_app": {"cut_line": cut,
            "partial_final_group_lines": partial}}
    if expect == "degraded-clock":
        cv = [(d["pre"], d["un"]) for r, g, _ in rounds for _, d in g if d["id"] == "app.counterview"]
        stale = ("UNSATISFIED", "svc.counter:UNKNOWN:OBSERVATION_STALE")
        k = cv.index(stale) if stale in cv else None
        c.update({
            "application_registry_ok_once": len(regs_ok) == 1 and not regs_ref,
            "no_launch_line": not launch_lines,
            "counterview_satisfied_before_the_anomaly": k is not None and k > 0 and all(x == ("SATISFIED", "NONE") for x in cv[:k]),
            "counterview_unsatisfied_on_stale_data_after_it": k is not None and all(x == stale for x in cv[k:]),
        })
        return c, info
    if expect != "launchpad":
        want = {"app-registry-dup": ("APP_DUPLICATE_ID", "2"), "app-false-exec": ("APP_EXEC_CLAIM_UNSUPPORTED", "1"),
                "app-unknown-req": ("APP_UNKNOWN_REQUIREMENT", "1")}[expect]
        c.update({
            "application_registry_refused_exactly": [(d["diag"], d["entry"], d["ex"]) for _, d in regs_ref] == [want + ("ABSENT",)]
                                                    and not regs_ok,
            "refusal_after_the_service_start": len(regs_ref) == 1 and op is not None and svc_reg is not None
                                               and first_status is not None and op < svc_reg < regs_ref[0][0] < first_status,
            "no_appinfo_and_no_launch_line": not infos and not launch_lines,
        })
        return c, info
    # ---------------------------------------------------------------- launchpad
    q_lines = [(i, m.groupdict()) for i, l in abr for m in [QUERY.match(l)] if m]
    discovery_infos = {i + 1 for i, _ in q_lines}
    script_start = min((i for i, _ in launch_lines), default=None)
    events = []  # in order: ("result", i, d) | ("trans", i, d) | ("routed", i, d) | ("query", i, d) | other
    malformed = []
    for i, l in launch_lines:
        if l.startswith("ABR|LAUNCHRESULT|"):
            d = parse_result(l)
            events.append(("result", i, d)) if d else malformed.append(l)
        elif TRANS.match(l):
            events.append(("trans", i, TRANS.match(l).groupdict()))
        elif ROUTED.match(l):
            events.append(("routed", i, ROUTED.match(l).groupdict()))
        elif QUERY.match(l):
            events.append(("query", i, QUERY.match(l).groupdict()))
        elif not (SUMMARY.match(l) or INJECT.match(l) or REFUSED_T.match(l) or STATE_L.match(l)):
            malformed.append(l)
    # requests in order, each: its transitions, then its result (or a routed/query line)
    reqs, pending, order_ok = [], [], True
    for kind, i, d in events:
        if kind == "trans":
            pending.append((i, d))
            continue
        reqs.append((kind, i, d, pending))
        if kind != "result" and pending:
            order_ok = False
        pending = []
    if pending:
        order_ok = False

    def trans_ok(d, tr):
        want = [("1", "SUBMITTED", "VALIDATED"), ("2", "VALIDATED", "NOT_EXECUTED")] if d["state"] == "NOT_EXECUTED" \
            else [("1", "SUBMITTED", "REFUSED")]
        got = [(t["seq"], t["frm"], t["to"]) for _, t in tr]
        contiguous = all(i2 == i1 + 1 for (i1, _), (i2, _) in zip(tr, tr[1:]))
        return got == want and all(t["req"] == d["req"] for _, t in tr) and contiguous

    results = [(i, d, tr) for kind, i, d, tr in reqs if kind == "result"]
    exp = expected_script()
    got_rows = [(d.get("req"), kind, d) for kind, _, d, _ in reqs]

    def row_ok(e, g):
        req, kind, over = e
        greq, gkind, gd = g
        if (req, kind) != (greq, gkind):
            return False
        return all(gd.get(k) == v for k, v in over.items())
    # the latest status round before a line
    def round_before(i):
        prior = [r for r, _, _ in rounds if max(x for x, _ in r.values()) < i]
        return prior[-1] if prior else None
    table = dict((a[0], a[4]) for a in h.APP_TABLE)

    def facts_match_round(i, d):
        if d["known"] != "YES" or d["target"] not in table:
            return True
        r = round_before(i)
        return r is not None and (d["prerequisites"], d["unavailable"]) == h.appinfo_expected(r, table[d["target"]].split(","))
    s = [(i, m.groupdict()) for i, l in abr for m in [SUMMARY.match(l)] if m]
    sm = s[0][1] if len(s) == 1 else {}
    n_ref = sum(1 for _, d, _ in results if d["state"] == "REFUSED")
    n_ne = sum(1 for _, d, _ in results if d["state"] == "NOT_EXECUTED")
    n_q = sum(1 for k, *_ in reqs if k == "query")
    n_r = sum(1 for k, *_ in reqs if k == "routed")
    inj = [(i, m.groupdict()) for i, l in abr for m in [INJECT.match(l)] if m]
    rt = [(i, m.groupdict()) for i, l in abr for m in [REFUSED_T.match(l)] if m]
    st = [(i, m.groupdict()) for i, l in abr for m in [STATE_L.match(l)] if m]
    first_req1 = next((d for _, d, _ in results if d["req"] == "1"), None)
    routed_answer = [lines[i + 1] for k, i, d, _ in reqs if k == "routed" and i + 1 < len(lines)]
    query_ok = all(
        i + 1 in [j for j, _ in infos] and (lambda inf: inf["id"] == d["target"] and round_before(i) is not None and
                                          (inf["pre"], inf["un"]) == h.appinfo_expected(round_before(i), table[inf["id"]].split(",")))
        (dict(infos)[i + 1]) for k, i, d, _ in reqs if k == "query" and d["op"] == "status")
    c.update({
        "application_registry_ok_once_before_the_script": len(regs_ok) == 1 and not regs_ref and script_start is not None
                                                          and regs_ok[0][0] < first_status < script_start,
        "every_launch_line_well_formed": not malformed,
        "transitions_right_before_their_result": order_ok and all(trans_ok(d, tr) for _, d, tr in results),
        "every_result_obeys_the_fact_rules": bool(results) and all(fact_rules_ok(d, public) for _, d, _ in results),
        "result_facts_agree_with_the_status_round": all(facts_match_round(i, d) for i, d, _ in results),
        "the_script_rows_exactly_as_designed": len(got_rows) == len(exp) and all(row_ok(e, g) for e, g in zip(exp, got_rows)),
        "discovery_answer_agrees_with_the_status_round": n_q == 1 and query_ok,
        "no_appinfo_outside_a_round_or_a_query": all(i in used or i in discovery_infos for i, _ in infos),
        "routed_request_answered_by_the_service_contract": n_r == 1 and routed_answer == ["ABR|SVCQUERY|op=start|target=svc.counter|result=REFUSED|reason=CAP_MISSING"],
        "summary_counts_equal_the_lines": bool(sm) and (int(sm["requests"]), int(sm["refused"]), int(sm["ne"]), int(sm["disc"]),
                                                         int(sm["routed"])) == (n_ref + n_ne + n_q + n_r, n_ref, n_ne, n_q, n_r)
                                          and (sm["executed"], sm["processes"], sm["executor"]) == ("0", "0", "ABSENT"),
        "injection_refused_and_state_unchanged": len(inj) == len(rt) == len(st) == 1 and first_req1 is not None
                                                 and inj[0][0] + 1 == rt[0][0] and rt[0][0] + 1 == st[0][0]
                                                 and (rt[0][1]["req"], rt[0][1]["frm"], rt[0][1]["to"], rt[0][1]["diag"])
                                                 == ("1", first_req1["state"], "RUNNING", "LAUNCH_INVALID_TRANSITION")
                                                 and st[0][1]["state"] == first_req1["state"] == "NOT_EXECUTED"
                                                 and bool(s) and s[0][0] < inj[0][0],
        "request_ids_in_script_order": [d.get("req") for _, _, d, _ in reqs] == [e[0] for e in exp],
    })
    info.update({"results": len(results), "requests": len(reqs), "malformed": malformed[:6]})
    return c, info


def judge_lines(lines, expect):
    checks, x = sp.common_checks(lines, PROD)
    rounds = x["rounds"]
    if expect != "degraded-clock":  # there the counter is UNKNOWN after the anomaly, by design (0.32b S16)
        checks["counter_available_and_increasing_every_round"] = bool(rounds) and all(
            sp.status_is(r["svc.counter"], "RUNNING", "AVAILABLE", "NONE", "LIVE") for r in rounds) and sp.increasing(rounds)
    checks["static_entries_unavailable_not_installed"] = bool(rounds) and all(
        sp.status_is(r[n], "DECLARED", "UNAVAILABLE", "NOT_INSTALLED", "UNKNOWN") for r in rounds for n in ("dev.net0", "svc.netmon"))
    lc, li = launch_checks(lines, expect)
    checks.update(lc)
    info = {"rounds": len(rounds), "end_of_capture": x["end_of_capture"], "stray": x["stray"][:6], **li}
    return checks, info


def run_vm(args):
    h.use_qemu(args.qemu_dir)
    kernel = Path(args.kernel).read_bytes()
    if hashlib.sha256(kernel).hexdigest() != args.expect_kernel_sha256.lower():
        print(f"REFUSED: kernel {args.kernel} has SHA-256 {hashlib.sha256(kernel).hexdigest()}, "
              f"expected {args.expect_kernel_sha256}; nothing was run")
        return 2
    run = h.EVIDENCE / "g033" / args.run_id
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
    meta = {"run_id": args.run_id, "label": "VM_MEASURED, DIAGNOSTIC launcher build (never accepted)",
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
                      **info}))
    return 0 if result["verdict"] == "PASS" else 1


def judge_existing(args):
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"REFUSED: {out} exists")
    serial = Path(args.serial)
    checks, info = judge_lines(h.serial_lines(serial), args.expect)
    out.mkdir(parents=True)
    result = {"verdict": "PASS" if all(checks.values()) else "FAIL", "checks": checks, **info,
              "source_serial": str(serial), "source_serial_sha256": h.sha256(serial),
              "evidence_label": "VM_MEASURED (judged again from a sealed run)"}
    (out / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    h.seal(out)
    print(json.dumps({"verdict": result["verdict"], "failed_checks": [k for k, v in checks.items() if not v], **info}))
    return 0 if result["verdict"] == "PASS" else 1


MODES = ("launchpad", "app-registry-dup", "app-false-exec", "app-unknown-req", "degraded-clock")


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
    r.add_argument("--expect", choices=MODES[:4], required=True)
    r.add_argument("--seconds", type=int, default=12)
    j = sub.add_parser("judge")
    j.add_argument("--serial", required=True)
    j.add_argument("--expect", choices=MODES, required=True)
    j.add_argument("--out", required=True)
    a = p.parse_args()
    return run_vm(a) if a.mode == "run" else judge_existing(a)


if __name__ == "__main__":
    raise SystemExit(main())
