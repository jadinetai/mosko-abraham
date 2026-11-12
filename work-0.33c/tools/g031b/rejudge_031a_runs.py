"""ABRAHAM 0.31b Step 3 proof: re-judge every sealed 0.31a harness run with the 0.31b judge.

  python -I -B tools/g031b/rejudge_031a_runs.py <out.json>

Reads (never writes) work-0.31/evidence/ABR-BOOT-001/<run>/: serial logs, host.json, results.json.final.
Each run is judged by the corrected judge under the profile it was originally measured with (0.31a,
or 0.29 for the 0.29 kernel and for runs made before profiles existed); C8 is taken from the run's own
final result (the seal itself was re-verified in Step 1). Expected: every run that was PASS stays PASS;
the two runs that FAILed by design (N007, N009) stay FAIL. A valid run turning FAIL here would mean
the corrected judge is too strict; a FAIL turning PASS would mean it is too lax. Both are reported.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

W31B = Path(__file__).resolve().parents[2]
RUNS = W31B.parent / "work-0.31" / "evidence" / "ABR-BOOT-001"

spec = importlib.util.spec_from_file_location("judge_0_31b", W31B / "tools" / "abr_boot_001.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def main():
    out = Path(sys.argv[1])
    rows, ok_all = {}, True
    for run in sorted(p for p in RUNS.iterdir() if p.is_dir()):
        final_path = run / "results.json.final"
        if not final_path.is_file():
            rows[run.name] = {"skipped": "no results.json.final (negative-hash control, judged differently)"}
            continue
        final = json.loads(final_path.read_text())
        host = json.loads((run / "host.json").read_text())
        profile = host.get("profile") or "0.29"
        args = argparse.Namespace(run_id=run.name, stable_seconds=15, profile=profile,
                                  expect_memtest=bool(host.get("expect_memtest")))
        result = h.judge(run / "serial.log", host, args)
        result["conditions"]["C8_evidence"] = final["conditions"]["C8_evidence"]
        new = h.verdict(result)
        same = new == final["verdict"]
        ok_all &= same
        rows[run.name] = {"profile": profile, "verdict_0_31a_judge": final["verdict"], "verdict_0_31b_judge": new,
                          "unchanged": same,
                          "failed_conditions_0_31b": sorted(c for c, v in result["conditions"].items() if v.get("pass") is False)}
    report = {"judge": str(W31B / "tools" / "abr_boot_001.py"), "runs_dir": str(RUNS), "runs": rows,
              "all_unchanged": ok_all}
    out.write_text(json.dumps(report, indent=1) + "\n")
    for k, v in rows.items():
        print(k, v)
    print("ALL VERDICTS UNCHANGED" if ok_all else "VERDICT CHANGED")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
