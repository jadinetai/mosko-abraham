"""ABRAHAM VM LAUNCHER 0.33.2: the evidence index cited by the 0.33.2 record (D-ABR-026). Post-campaign tool; not under test.

  python -I -B tools/evidence_index_vml.py

Writes EVIDENCE_INDEX_VML_0.33.2.sha256: `<sha256>  <path>` for every file of the tree (paths relative to
vmlauncher-0.33.2), except build output (target/), the audit package folder (evidence/review/, made after the index)
and the index itself; then the home files the stage rests on, as `../<path>`. Re-checks every run seal and the
campaign seal on the way, and prints the index's own digest. Standard library only.
"""
import hashlib
import json
from pathlib import Path

VML = Path(__file__).resolve().parents[1]
HOME = VML.parent
OUT = VML / "EVIDENCE_INDEX_VML_0.33.2.sha256"
HOME_FILES = ["MOSKO_ABRAHAM_033_VM_LAUNCHER_DIRECTIVE_2026-11-09.md", "MOSKO_ABRAHAM_033C_FINAL_AUDIT_DIRECTIVE_2026-11-10.md",
              "DECISIONS.md", "PATCH_NOTES_0.33c.md", "test-records/TR-0045.md", "test-records/TR-0046.md"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    rows, seals, bad, partial = [], 0, [], []
    for p in sorted(VML.rglob("*")):
        rel = p.relative_to(VML)
        if not p.is_file() or rel.parts[0] == "target" or rel.as_posix().startswith("evidence/review/") or p == OUT:
            continue
        if "__pycache__" in rel.parts:
            continue
        rows.append(f"{sha(p)}  {rel.as_posix()}")
        if p.name in ("RUN_SHA256SUMS.json", "CAMPAIGN_SHA256SUMS.json"):
            listed = json.loads(p.read_text())
            if rel.parts[:2] == ("evidence", "dev") and rel.parent.name.startswith("dry-run-"):
                # Development dry runs: only their campaign.json, seal and source manifest were kept from the scratch
                # folder; the kept files must still match the seal.
                kept = {n: d for n, d in listed.items() if (p.parent / n).is_file()}
                partial.append({"folder": rel.parent.as_posix(), "listed": len(listed), "kept": len(kept)})
                listed = kept
            seals += 1
            for n, d in listed.items():
                if not (p.parent / n).is_file() or sha(p.parent / n) != d:
                    bad.append(f"{rel.parent.as_posix()}/{n}")
    for f in HOME_FILES:
        rows.append(f"{sha(HOME / f)}  ../{f}")
    OUT.write_text("\n".join(rows) + "\n", encoding="ascii")
    print(json.dumps({"index": str(OUT), "sha256": sha(OUT), "rows": len(rows), "seals_rechecked": seals,
                      "seal_mismatches": bad, "partial_dry_run_copies": partial}))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
