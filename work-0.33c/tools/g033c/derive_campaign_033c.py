"""ABRAHAM 0.33c: derive the reproduction driver tools/g033c/campaign_033c.py from the 0.33 campaign driver.

  python -I -B tools/g033c/derive_campaign_033c.py

Every entry, command, expected exit code and post-check of tools/g033/campaign_033.py is kept byte for byte. Only the
lines that tie the driver to its old location change; each substitution must apply exactly once, or nothing is
written. The substitutions and both digests go to tools/g033c/campaign_033c.DERIVATION.json, with a unified diff.
"""
import difflib
import hashlib
import json
from pathlib import Path

C = Path(__file__).resolve().parents[2]
SRC = C / "tools" / "g033" / "campaign_033.py"
DST = C / "tools" / "g033c" / "campaign_033c.py"
SUBS = [
    ('OUT = W / "evidence" / "campaign-033"\n', 'OUT = W / "evidence" / "campaign-033c"\n',
     "the reproduction writes its own campaign folder"),
    ('CP_032B = W / "evidence" / "start" / "ABR-0.33-V001" / "CHECKPOINT_work-0.32b.sha256"',
     'CP_032B = HOME / "work-0.33" / "evidence" / "start" / "ABR-0.33-V001" / "CHECKPOINT_work-0.32b.sha256"',
     "the 0.32b checkpoint is read where TR-0041 recorded it (work-0.33 is never written)"),
    ('json.loads((W / "evidence" / "campaign-033" / "BUILD_MANIFEST.json").read_text())["kernels"][k]["sha256"]',
     'json.loads((W / "evidence" / "campaign-033c" / "BUILD_MANIFEST.json").read_text())["kernels"][k]["sha256"]',
     "kernel digests come from this campaign's own frozen manifest"),
    ('    P = "ABR-0.33-"\n    W032 = HOME', '    P = "ABR-0.33c-"\n    W032 = HOME',
     "new run ids in the main entries (ids are never reused); the supplement and demo entries are not used"),
]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    src = SRC.read_text(encoding="utf-8")
    out = src
    for a, b, _ in SUBS:
        if out.count(a) != 1:
            raise SystemExit(f"REFUSED: substitution does not apply exactly once: {a!r}")
        out = out.replace(a, b, 1)
    head = ('# DERIVED by tools/g033c/derive_campaign_033c.py from tools/g033/campaign_033.py (ABRAHAM 0.33c, D-ABR-026).\n'
            '# Entries, commands, expected exit codes and post-checks are unchanged; see campaign_033c.DERIVATION.json.\n')
    out = head + out
    DST.write_text(out, encoding="utf-8", newline="\n")
    diff = "".join(difflib.unified_diff(src.splitlines(True), out.splitlines(True), "tools/g033/campaign_033.py",
                                        "tools/g033c/campaign_033c.py"))
    (DST.with_suffix(".diff")).write_text(diff, encoding="utf-8", newline="\n")
    rec = {"source": str(SRC), "source_sha256": sha(SRC.read_bytes()), "derived": str(DST),
           "derived_sha256": sha(DST.read_bytes()), "substitutions": [{"from": a, "to": b, "why": w} for a, b, w in SUBS],
           "diff_lines": diff.count("\n")}
    DST.with_name("campaign_033c.DERIVATION.json").write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps({k: rec[k] for k in ("source_sha256", "derived_sha256", "diff_lines")}))


if __name__ == "__main__":
    main()
