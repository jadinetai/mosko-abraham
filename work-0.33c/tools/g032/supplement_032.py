"""ABRAHAM 0.32 campaign supplement: recorded runs made AFTER `campaign close` (TR-0037).

  python -I -B tools/g032/supplement_032.py run [IDS...]

The closed campaign (evidence/campaign-032/campaign.json) is never changed. Supplementary entries follow the same
rules as campaign entries: a fixed command, an expected exit code and a post-check, all written down here before
they run, and run ids that are never reused. Console output goes to evidence/campaign-032-supplement/<id>.console.txt,
the summary to supplement.json. Each run also records the source tree (kernel/, tools/, boot/) against
SOURCE_MANIFEST_END.json of the closed campaign, so every change made after close is listed next to the run.

Entries:
  ABR-0.32-J005  the corrected C12 judge self-test on the same W001 copies. J001 was UNEXPECTED (40 of 41): its
                 end-of-capture control removed heartbeats along with the cut round, so C5 failed while C12 passed.
                 Expected: 42 of 42, both end-of-capture controls PASS with the cut reported.
Standard library only.
"""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

W = Path(__file__).resolve().parents[2]
EV = W / "evidence"
OUT = EV / "campaign-032-supplement"
PY = [sys.executable, "-I", "-B"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def J(p):
    return json.loads(Path(p).read_text())


def j005_ok():
    r = J(EV / "g032" / "ABR-0.32-J005" / "report.json")
    c = r["cases"]
    return (r["all_ok"] and r["cases_total"] == 42 and c["end_of_capture_cut_control"]["ok"]
            and c["end_of_capture_partial_round_control"]["ok"])


def entries():
    return [
        ("ABR-0.32-J005", "harness: corrected C12 falsifications on W001 copies (after J001), each failing for its intended reason",
         lambda: PY + ["tools/g032/judge_selftest_032.py", str(EV / "ABR-BOOT-001" / "ABR-0.32-W001"), str(EV / "g032" / "ABR-0.32-J005")],
         0, EV / "g032" / "ABR-0.32-J005", j005_ok),
    ]


def tree_manifest():
    files = {}
    for d in ("kernel", "tools", "boot"):
        for p in sorted((W / d).rglob("*")):
            if p.is_file() and not ({"target", "__pycache__"} & set(p.relative_to(W).parts)):
                files[p.relative_to(W).as_posix()] = sha(p)
    return files


def run(selected):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "supplement.json"
    summary = J(path) if path.exists() else {"runs": [], "closed_campaign": str(EV / "campaign-032" / "campaign.json"),
                                              "closed_campaign_sha256": sha(EV / "campaign-032" / "campaign.json")}
    done = {r["id"] for r in summary["runs"]}
    end = J(EV / "campaign-032" / "SOURCE_MANIFEST_END.json")
    for rid, purpose, build, expected, evidence, post in entries():
        if selected and rid not in selected:
            continue
        if rid in done or evidence.exists():
            print(f"SKIP {rid}: already run (ids are never reused)", flush=True)
            continue
        now = tree_manifest()
        changed = {"changed": sorted(k for k in end if k in now and now[k] != end[k]),
                   "added": sorted(set(now) - set(end)), "removed": sorted(set(end) - set(now))}
        cmd = build()
        started = datetime.now(timezone.utc).isoformat()
        p = subprocess.run(cmd, cwd=W, capture_output=True, text=True)
        console = OUT / f"{rid}.console.txt"
        console.write_text(p.stdout + ("\n--- stderr ---\n" + p.stderr if p.stderr else ""))
        try:
            post_ok = post() if post else None
        except Exception as e:  # noqa: BLE001
            post_ok = False
            console.write_text(console.read_text() + f"\n--- post-check error ---\n{e!r}\n")
        rec = {"id": rid, "purpose": purpose, "command": [str(c) for c in cmd], "expected_exit": expected, "exit": p.returncode,
               "post_check": None if post is None else bool(post_ok),
               "as_expected": p.returncode == expected and post_ok is not False, "started_utc": started,
               "ended_utc": datetime.now(timezone.utc).isoformat(), "console_sha256": sha(console),
               "source_since_campaign_close": changed}
        summary["runs"].append(rec)
        path.write_text(json.dumps(summary, indent=1) + "\n")
        print(f"{'OK  ' if rec['as_expected'] else 'UNEXPECTED'} {rid} exit={p.returncode} expected={expected}"
              f"{'' if post is None else ' post=' + str(bool(post_ok))}  {purpose}", flush=True)
        print(json.dumps(changed, indent=1), flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        run(set(sys.argv[2:]))
    else:
        raise SystemExit(__doc__)
