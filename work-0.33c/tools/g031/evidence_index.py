"""ABRAHAM 0.31a evidence index and seal re-verification.

  python -I tools/g031/evidence_index.py

1. Re-hashes every member of every RUN_SHA256SUMS.json under work-0.31/evidence (any depth).
2. Writes work-0.31/EVIDENCE_INDEX_0.31a.sha256 ("<sha256>  <kind>  <path from Documents\\Abraham>"):
   owner records, design and review documents, kernel sources, tools, boot config, kernel binaries,
   every run seal, the campaign files and the source diff. Refuses to overwrite an existing index.
   TR-0033 and test-records/INDEX.md are not in it: the record cites this index's digest.
Standard library only.
"""
import hashlib
import json
import sys
from pathlib import Path

W31 = Path(__file__).resolve().parents[2]
HOME = W31.parent
OUT = W31 / "EVIDENCE_INDEX_0.31a.sha256"
SKIP = {"target", "__pycache__"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rel(p):
    return str(Path(p).resolve().relative_to(HOME))


def main():
    if OUT.exists():
        raise SystemExit(f"REFUSED: {OUT} exists")
    seals, members, bad = 0, 0, []
    for s in sorted((W31 / "evidence").rglob("RUN_SHA256SUMS.json")):
        seals += 1
        for name, digest in json.loads(s.read_text()).items():
            members += 1
            f = s.parent / name
            if not f.is_file() or sha(f) != digest:
                bad.append(rel(f))
    entries = []
    add = lambda kind, p: entries.append((sha(p), kind, rel(p)))
    add("freeze-manifest", HOME / "frozen" / "ABR-BOOT-001-accepted" / "FREEZE_MANIFEST.sha256")
    add("signoff-index-0.29", HOME / "work-0.29" / "EVIDENCE_INDEX_0.29_SIGNOFF.sha256")
    add("decisions", HOME / "DECISIONS.md")
    add("baseline", HOME / "ABRAHAM_0.2_BASELINE.md")
    add("directive", HOME / "MOSKO_ABRAHAM_029_ECHO_INDEPENDENT_AUDIT_2026-11-05.md")
    add("directive", HOME / "MOSKO_ABRAHAM_NEW_CLAUDE_THREAD_HANDOFF_2026-11-05.md")
    for p in [W31 / "README.md", W31 / "COPY_MANIFEST_FROM_0.29.json", *sorted((W31 / "docs").glob("*.md"))]:
        add("document", p)
    for d, kind in (("kernel", "kernel-source"), ("tools", "tool"), ("boot", "boot-config")):
        for p in sorted((W31 / d).rglob("*")):
            if p.is_file() and not (SKIP & set(p.relative_to(W31).parts)):
                add(kind, p)
    manifest = json.loads((W31 / "evidence" / "campaign-031a" / "BUILD_MANIFEST.json").read_text())
    for k, v in manifest["kernels"].items():
        p = Path(v["path"]) if Path(v["path"]).is_absolute() else W31 / v["path"]
        if sha(p) != v["sha256"]:
            bad.append(f"kernel {k} changed since BUILD_MANIFEST")
        add("kernel-binary", p)
    for p in sorted((W31 / "build" / "diag").glob("build-info-*.json")):
        add("build-info", p)
    add("build-info", W31 / "build" / "build-info.json")
    for s in sorted((W31 / "evidence").rglob("RUN_SHA256SUMS.json")):
        add("run-seal", s)
    for p in sorted((W31 / "evidence" / "campaign-031a").glob("*")):
        if p.is_file():
            add("campaign", p)
    add("review", W31 / "evidence" / "review" / "0.31a_SOURCE_DIFF.patch")
    OUT.write_text("".join(f"{d}  {k}  {p}\n" for d, k, p in entries))
    kinds = {}
    for _, k, _ in entries:
        kinds[k] = kinds.get(k, 0) + 1
    report = {"run_seals": seals, "sealed_members_rehashed": members, "mismatches": bad,
              "index": rel(OUT), "index_entries": len(entries), "per_kind": kinds, "index_sha256": sha(OUT)}
    print(json.dumps(report, indent=1))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
