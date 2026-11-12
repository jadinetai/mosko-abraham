"""ABRAHAM 0.33: re-judge every sealed harness run of an earlier tree with the 0.33 harness (the C13 addition must not
change any earlier verdict). Generalized from tools/g032b/rejudge_032_runs.py; the rules are unchanged.

  python -I -B tools/g033/rejudge_runs.py <tree, e.g. work-0.32b> <out.json>

For every run folder under <tree>/evidence/ABR-BOOT-001 that has a sealed results.json.final, the run's own
serial logs and host.json are judged again (read-only) by this tree's tools/abr_boot_001.py under the profile the
run was recorded with, and the verdict is compared with the recorded one. Hardening must not change any verdict of
genuine evidence. Expected, fixed before the run: every verdict unchanged. C8 is taken from the sealed final result
(the evidence seal is not re-evaluated). Writes only <out.json>. Standard library only.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

W = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(W / "tools"))
import abr_boot_001 as h  # noqa: E402



def main():
    SRC = W.parent / sys.argv[1] / "evidence" / "ABR-BOOT-001"
    out = Path(sys.argv[2])
    rows, changed = [], []
    for run in sorted(p for p in SRC.iterdir() if p.is_dir()):
        final_p = run / "results.json.final"
        if not final_p.is_file():
            rows.append({"run": run.name, "skipped": "no results.json.final (loader-refusal control or refused run)"})
            continue
        final = json.loads(final_p.read_text())
        host = json.loads((run / "host.json").read_text())
        prof = final.get("profile")
        args = argparse.Namespace(run_id=f"rejudge-{run.name}", stable_seconds=15, profile=prof,
                                  expect_memtest=bool(host.get("expect_memtest")))
        res = h.judge(run / "serial.log", copy.deepcopy(host), args)
        res["conditions"]["C8_evidence"] = final["conditions"]["C8_evidence"]
        res["profile"] = prof
        now = h.verdict(res)
        row = {"run": run.name, "profile": prof, "recorded": final["verdict"], "rejudged": now, "unchanged": now == final["verdict"],
               "failed_now": sorted(c for c, v in res["conditions"].items() if v.get("pass") is False)}
        rows.append(row)
        if not row["unchanged"]:
            changed.append(run.name)
    judged = [r for r in rows if "rejudged" in r]
    report = {"source": str(SRC), "judge": str(W / "tools" / "abr_boot_001.py"), "judge_sha256": h.sha256(W / "tools" / "abr_boot_001.py"),
              "runs": rows, "judged": len(judged), "changed": changed,
              "verdict": "VERDICTS UNCHANGED" if judged and not changed else "VERDICTS CHANGED"}
    out.write_text(json.dumps(report, indent=1) + "\n")
    for r in rows:
        print(r)
    print(report["verdict"], f"{len(judged)} judged, {len(changed)} changed")
    return 0 if judged and not changed else 1


if __name__ == "__main__":
    sys.exit(main())
