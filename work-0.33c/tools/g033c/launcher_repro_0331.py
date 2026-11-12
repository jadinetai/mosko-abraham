"""ABRAHAM 0.33c Phase 2 (D-ABR-026): reproduce the launcher findings on the TESTED launcher 0.33.1 itself.

  python -I -B tools/g033c/launcher_repro_0331.py

Runs a fixed subset of the 0.33.1 campaign's own entry functions (vmlauncher-0.33.1/tools/campaign_vml.py, imported
read-only; its EXPECT texts and checks are used unchanged) against the 0.33.1 program c09f1cbf, writing only into
work-0.33c/evidence/launcher-0.33.1-repro, with new run ids. Plus one entry of its own, fixed here before any run:
  D001  a launcher-contract failure and a services failure stay distinct: on a falsified launchpad log (J007
        launchpad/result_claims_execution) the 0.33.1 offline check says contract INCONSISTENT (exit 6) with every
        service check true; on the short-freeze run P003 the result is SERVICES_NOT_AS_DESIGNED (exit 10) with the
        contract CONSISTENT.
Standard library only.
"""
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

C = Path(__file__).resolve().parents[2]
HOME = C.parent
V1 = HOME / "vmlauncher-0.33.1"
spec = importlib.util.spec_from_file_location("campaign_vml_0331", V1 / "tools" / "campaign_vml.py")
cv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cv)

OUT = C / "evidence" / "launcher-0.33.1-repro"
SUBSET = ["X001", "F001", "F002", "F003", "A001", "A004", "P001", "P003", "P004", "X002"]
OWN = {"D001": "a contract failure and a services failure stay distinct: the J007 falsification "
               "launchpad/result_claims_execution gives contract INCONSISTENT, exit 6, every service check true (0.33.1 "
               "offline check); P003 of this run gives SERVICES_NOT_AS_DESIGNED, exit 10, contract CONSISTENT"}


def e_D001(ctx):
    log = HOME / "work-0.33" / "evidence" / "g033" / "ABR-0.33-J007" / "launchpad" / "result_claims_execution" / "serial.log"
    r = subprocess.run([str(cv.EXE), "--check-serial", str(log), "--kernel", "launchpad"], capture_output=True, text=True)
    d = json.loads(r.stdout)
    p3 = json.loads((cv.RUNS / (cv.P + "P003") / "launch.json").read_text())
    obs = {"falsified_log": str(log), "exit": r.returncode, "contract": d["launcher_contract"],
           "service_checks": d["service_checks"], "P003_result": p3.get("result"), "P003_exit": p3.get("exit_code"),
           "P003_contract": p3.get("verdicts", {}).get("launcher_contract"), "P003_services": p3.get("verdicts", {}).get("services")}
    ok = (r.returncode == 6 and d["launcher_contract"] == "INCONSISTENT" and all(d["service_checks"].values())
          and p3.get("result") == "SERVICES_NOT_AS_DESIGNED" and p3.get("exit_code") == 10
          and obs["P003_contract"] == "CONSISTENT" and obs["P003_services"] == "PROBLEMS")
    return obs, ok


def main():
    if OUT.exists():
        raise SystemExit(f"REFUSED: {OUT} exists; ids are never reused")
    cv.OUT = OUT
    cv.RUNS = OUT / "runs"
    cv.MENU_RUNS = OUT / "menu-runs"
    cv.P = "VML-0.33c-R-"
    OUT.mkdir(parents=True)
    cv.RUNS.mkdir()
    expect = {e: cv.EXPECT[e] for e in SUBSET}
    expect.update(OWN)
    (OUT / "EXPECTED.json").write_text(json.dumps(expect, indent=1) + "\n")
    rec = {"what": "launcher 0.33.1 findings reproduced on the tested program (D-ABR-026 Phase 2)", "program_sha256": cv.sha(cv.EXE),
           "campaign_tool": str(V1 / "tools" / "campaign_vml.py"), "campaign_tool_sha256": cv.sha(V1 / "tools" / "campaign_vml.py"),
           "started_utc": datetime.now(timezone.utc).isoformat(), "runs": []}
    ctx = {}
    order = SUBSET[:-1] + ["D001", "X002"]
    for e in order:
        t0 = time.monotonic()
        print(f"{cv.P}{e}: {expect[e]}", flush=True)
        try:
            obs, ok = (e_D001 if e == "D001" else getattr(cv, f"e_{e}"))(ctx)
            err = None
        except Exception as x:  # recorded, never hidden
            obs, ok, err = {}, False, repr(x)
        row = {"id": cv.P + e, "expected": expect[e], "observed": obs, "as_expected": bool(ok) and err is None, "error": err,
               "seconds": round(time.monotonic() - t0, 1)}
        rec["runs"].append(row)
        print(f"    -> {'AS EXPECTED' if row['as_expected'] else 'UNEXPECTED'}{'  ' + err if err else ''}", flush=True)
        (OUT / "campaign.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    rec["ended_utc"] = datetime.now(timezone.utc).isoformat()
    rec["unexpected"] = [r["id"] for r in rec["runs"] if not r["as_expected"]]
    (OUT / "campaign.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    sums = {p.relative_to(OUT).as_posix(): cv.sha(p) for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "CAMPAIGN_SHA256SUMS.json"}
    (OUT / "CAMPAIGN_SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n")
    print(f"{len(rec['runs']) - len(rec['unexpected'])}/{len(rec['runs'])} as expected; unexpected: {rec['unexpected']}")
    return 0 if not rec["unexpected"] else 1


if __name__ == "__main__":
    sys.exit(main())
