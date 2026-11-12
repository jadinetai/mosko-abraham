"""ABRAHAM 0.33 launchpad demonstration on the VM, watched live (D-ABR-022 Q6; for the operator).

  python -I -B tools/g033/launchpad_demo.py --run-id ABR-0.33-DEMO-<n> [--accel whpx|tcg] [--all] [--seconds N]

Boots the real DIAGNOSTIC kernel diag-launchpad (pinned by its digest in evidence/campaign-033/BUILD_MANIFEST.json)
in QEMU 11.1.0 with the harness's own staging, firmware and verified timer opt-out, and streams the kernel's serial
console to this terminal while it runs:
  - the application registry and the APPINFO lines of each status round;
  - the 17 requests of the fixed script, their transitions and results, each followed by one plain-English line;
  - the routed service request, the summary and the refused RUNNING transition.
`--all` also shows every heartbeat and service status line. The kernel has no input path (D-ABR-022): it runs its
compiled script and nothing else; requests of your own are for the hosted demonstration
(`cd kernel/hosttest; cargo run --example launchpad -- "start app.counterview"`).
At the end the captured log is judged by tools/g033/launch_probe.py (mode launchpad); the run folder
evidence/demo/<run-id>/ is sealed. Exit 0 only if the judge PASSES. Label: VM_MEASURED (a demonstration run).
Standard library only. Nothing is downloaded.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
W = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "g033"))
import abr_boot_001 as h  # noqa: E402
import launch_probe as lp  # noqa: E402

QEMU = "C:/Users/XxUnd/abraham-toolchain/qemu/11.1.0-weil-20260811"
EFI = W / "third_party" / "limine-12.9.6" / "extracted" / "limine-binary" / "BOOTX64.EFI"
WHY = {"LAUNCH_ID_NOT_INCREASING": "its request number is not greater than the last one (ordering, not authentication)",
       "LAUNCH_OPERATION_UNKNOWN": "the operation word is not one Abraham knows for applications",
       "LAUNCH_TARGET_UNKNOWN": "no application of exactly that name is in the registry",
       "LAUNCH_REGISTRY_REFUSED": "the application registry was refused at boot",
       "LAUNCH_CAP_MISSING": "a privileged request with no capability (none can exist yet)",
       "LAUNCH_NO_AUTHORITY": "a capability was named, but no authority mechanism exists"}
SHOW = ("ABRAHAM", "ABR|STATE|OPERATIONAL", "ABR|SVC|registry", "ABR|APP", "ABR|LAUNCH", "ABR|SVCQUERY",
        "ABR|DIAG|injecting=launch", "ABR|FAULT")


class Out:
    """Prints to the terminal; if the terminal goes away (a closed pipe), stops printing but lets the run finish, so
    QEMU is always shut down and the run folder is always judged and sealed (found in ABR-0.33-DEV-DEMO1)."""
    alive = True

    @classmethod
    def say(cls, text=""):
        if not cls.alive:
            return
        try:
            print(text, flush=True)
        except (BrokenPipeError, OSError):
            cls.alive = False


def explain(l):
    d = lp.parse_result(l)
    if not d:
        return None
    why = WHY.get(d["diag"], "the text does not follow the request grammar" if d["diag"].startswith("LAUNCH_PARSE_") else d["diag"])
    extra = "; its prerequisites are also unmet" if d["prerequisites"] == "UNSATISFIED" else (
        "; prerequisites met, but nothing can execute in 0.33" if d["prerequisites"] == "SATISFIED" else "")
    head = f"REFUSED at {d['stage']}" if d["state"] == "REFUSED" else f"validated, then NOT EXECUTED at {d['stage']}"
    return f"      = {head}: {why}{extra}. executed={d['executed']}, process={d['process']}."


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--accel", choices=("whpx", "tcg"), default="whpx")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seconds", type=int, default=6, help="keep running this long after the script finished")
    a = ap.parse_args()
    h.use_qemu(QEMU)
    bm = json.loads((W / "evidence" / "campaign-033" / "BUILD_MANIFEST.json").read_text())["kernels"]["launchpad"]
    kpath = W / bm["path"]
    kernel = kpath.read_bytes()
    if hashlib.sha256(kernel).hexdigest() != bm["sha256"]:
        print(f"REFUSED: {kpath} is not the campaign's diag-launchpad kernel {bm['sha256']}; nothing was run")
        return 2
    run = W / "evidence" / "demo" / a.run_id
    if run.exists():
        raise SystemExit(f"REFUSED: {run} exists (use a new run id)")
    esp = run / "esp"
    (esp / "EFI" / "BOOT").mkdir(parents=True)
    (esp / "boot" / "limine").mkdir(parents=True)
    shutil.copyfile(EFI, esp / "EFI" / "BOOT" / "BOOTX64.EFI")
    (esp / "boot" / "abraham-kernel").write_bytes(kernel)
    conf = h.LIMINE_CONF.read_text(encoding="ascii").replace("{KERNEL_BLAKE2B}", hashlib.blake2b(kernel).hexdigest())
    (esp / "boot" / "limine" / "limine.conf").write_text(conf, encoding="ascii", newline="\n")
    shutil.copyfile(h.FW_VARS, run / "vars.fd")
    serial = run / "serial.log"
    port = h.free_port()
    cpu = "host" if a.accel == "whpx" else "max"
    command = h.qemu_command(a.accel, cpu, run, esp, port, serial) + ["-S"]
    Out.say(f"ABRAHAM 0.33 launchpad on the VM: QEMU 11.1.0 {a.accel.upper()}, kernel diag-launchpad {bm['sha256'][:16]}...")
    Out.say(f"evidence: {run}\n")
    meta = {"run_id": a.run_id, "label": "VM_MEASURED, DIAGNOSTIC launcher build, operator demonstration",
            "accelerator": a.accel, "kernel": str(kpath), "kernel_sha256": bm["sha256"], "qemu_command": command,
            "started_utc": h.utc()}
    t0 = time.monotonic()
    with open(run / "qemu-stderr.txt", "wb") as err:
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err)
        try:
            meta["timer_throttling_opt_out"] = h.opt_out_timer_throttling(proc.pid)
            qmp = h.Qmp(port, run / "qmp.jsonl", t0)
            qmp.command("cont")
            meta["script_finished"] = stream(a, serial, t0)
            meta["status"] = qmp.command("query-status").get("return")
            qmp.command("quit")
            meta["qemu_exit"] = proc.wait(timeout=20)
            meta["qmp_events"] = qmp.events
        finally:
            if proc.poll() is None:  # never leave a QEMU behind
                proc.kill()
                meta["qemu_killed_by_the_viewer"] = True
    return finish(run, serial, meta)


def stream(a, serial, t0):
    """Print the serial console while it grows. True once the script's last line (request 1's state after the forced
    transition) has appeared and `a.seconds` more have passed; False on the 180 s limit."""
    done_at, seen = None, 0
    while time.monotonic() - t0 < 180:
        complete = h.serial_lines(serial)[:-1]  # the last element may be a line still being written
        for l in complete[seen:]:
            if a.all or l.startswith(SHOW):
                if l.startswith("ABR|LAUNCH|req=") and "|seq=1|" in l:
                    Out.say()
                Out.say("  " + l)
                e = explain(l) if l.startswith("ABR|LAUNCHRESULT|") else None
                if e:
                    Out.say(e)
        seen = len(complete)
        if done_at is None and any(l.startswith("ABR|LAUNCH|req=1|state=") for l in complete):
            done_at = time.monotonic()
        if done_at is not None and time.monotonic() - done_at >= a.seconds:
            return True
        time.sleep(0.2)
    return False


def finish(run, serial, meta):
    meta["ended_utc"] = h.utc()
    checks, info = lp.judge_lines(h.serial_lines(serial), "launchpad")
    opt = meta.get("timer_throttling_opt_out")
    checks["timer_opt_out_verified"] = isinstance(opt, dict) and opt.get("ok") is True
    checks["script_finished"] = meta.get("script_finished") is True
    checks["qemu_quit_cleanly"] = not meta.get("qemu_killed_by_the_viewer")
    result = {"verdict": "PASS" if all(checks.values()) else "FAIL", "checks": checks, **info,
              "evidence_label": "VM_MEASURED (operator demonstration)"}
    (run / "demo.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    (run / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    h.seal(run)
    failed = [k for k, v in checks.items() if not v]
    Out.say(f"\njudged by launch_probe (launchpad): {result['verdict']}" + (f", failed: {failed}" if failed else ""))
    Out.say("nothing executed: the executor is ABSENT in 0.33; real execution is 0.4.")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
