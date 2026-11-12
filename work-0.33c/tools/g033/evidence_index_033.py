"""ABRAHAM 0.33 evidence index and seal re-verification (written after `campaign close`).

  python -I -B tools/g033/evidence_index_033.py

The 0.32b index tool (tools/g032b/evidence_index_032b.py) with the 0.33 inputs.
1. Re-hashes every member of every RUN_SHA256SUMS.json under work-0.33/evidence (any depth).
2. Writes work-0.33/EVIDENCE_INDEX_0.33.sha256 ("<sha256>  <kind>  <path from Documents\\Abraham>"):
   - owner records and directives, Echo's 0.32b final review, and the baseline;
   - the earlier indexes it builds on (freeze, 0.29 sign-off, 0.31a, 0.31b, 0.32, 0.32b, the 0.32b gate) and the
     audit-package digests;
   - the records TR-0039, TR-0040, TR-0041;
   - documents, kernel sources, tools, boot config;
   - kernel binaries (campaign BUILD_MANIFEST, including the pinned reference kernels), build-info;
   - every run seal, and every evidence file NOT covered by a run seal.
   evidence/packaging-033/ (consoles written after this index) is excluded. Refuses to overwrite. The final 0.33
   record and test-records/INDEX.md are not in it: the record cites this index's digest.
Standard library only.
"""
import hashlib
import json
import sys
from pathlib import Path

W = Path(__file__).resolve().parents[2]
HOME = W.parent
OUT = W / "EVIDENCE_INDEX_0.33.sha256"
SKIP = {"target", "__pycache__"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rel(p):
    return str(Path(p).resolve().relative_to(HOME))


def main():
    if OUT.exists():
        raise SystemExit(f"REFUSED: {OUT} exists")
    ev = W / "evidence"
    seals = sorted(ev.rglob("RUN_SHA256SUMS.json"))
    sealed_dirs = {s.parent for s in seals}
    members, bad = 0, []
    for s in seals:
        for name, digest in json.loads(s.read_text()).items():
            members += 1
            f = s.parent / name
            if not f.is_file() or sha(f) != digest:
                bad.append(rel(f))
    entries = []
    add = lambda kind, p: entries.append((sha(p), kind, rel(p)))
    for name in ("MOSKO_ABRAHAM_032B_CORRECTIVE_DIRECTIVE_2026-11-08.md", "MOSKO_ABRAHAM_033_PREPARATION_DIRECTIVE_2026-11-08.md"):
        add("directive", HOME / name)
    add("independent-review", HOME / "MOSKO_ABRAHAM_032B_ECHO_FINAL_AUDIT_2026-11-08.md")
    add("decisions", HOME / "DECISIONS.md")
    add("baseline", HOME / "ABRAHAM_0.2_BASELINE.md")
    add("design-home-copy", HOME / "ABRAHAM_0.33_DESIGN.md")
    add("gate-report", HOME / "0.32b_ACCEPTANCE_GATE.md")
    add("freeze-manifest", HOME / "frozen" / "ABR-BOOT-001-accepted" / "FREEZE_MANIFEST.sha256")
    add("signoff-index-0.29", HOME / "work-0.29" / "EVIDENCE_INDEX_0.29_SIGNOFF.sha256")
    add("evidence-index-0.31a", HOME / "work-0.31" / "EVIDENCE_INDEX_0.31a.sha256")
    add("evidence-index-0.31b", HOME / "work-0.31b" / "EVIDENCE_INDEX_0.31b.sha256")
    add("evidence-index-0.32", HOME / "work-0.32" / "EVIDENCE_INDEX_0.32.sha256")
    add("evidence-index-0.32b", HOME / "work-0.32b" / "EVIDENCE_INDEX_0.32b.sha256")
    add("audit-zip-0.32b", HOME / "work-0.32b" / "evidence" / "review" / "ABRAHAM_0.32b_ECHO_AUDIT.zip.sha256")
    add("gate-index-0.32b", HOME / "gate-0.32b" / "GATE_EVIDENCE_INDEX_0.32b.sha256")
    add("final-audit-zip-0.32b", HOME / "gate-0.32b" / "review" / "ABRAHAM_0.32b_FINAL_AUDIT.zip.sha256")
    for tr in ("TR-0039", "TR-0040", "TR-0041"):
        add("record", HOME / "test-records" / f"{tr}.md")
    add("record-output", HOME / "test-records" / "TR-0040.verify.out.txt")
    for p in [W / "README.md", W / "COPY_MANIFEST_FROM_0.32b.json", *sorted((W / "docs").glob("*.md"))]:
        add("document", p)
    for d, kind in (("kernel", "kernel-source"), ("tools", "tool"), ("boot", "boot-config")):
        for p in sorted((W / d).rglob("*")):
            if p.is_file() and not (SKIP & set(p.relative_to(W).parts)):
                add(kind, p)
    manifest = json.loads((ev / "campaign-033" / "BUILD_MANIFEST.json").read_text())
    for k, v in manifest["kernels"].items():
        p = Path(v["path"]) if Path(v["path"]).is_absolute() else W / v["path"]
        if sha(p) != v["sha256"]:
            bad.append(f"kernel {k} changed since BUILD_MANIFEST")
        add("kernel-binary", p)
    for p in [W / "build" / "build-info.json", *sorted((W / "build" / "diag").glob("build-info-*.json"))]:
        add("build-info", p)
    for s in seals:
        add("run-seal", s)
    for p in sorted(ev.rglob("*")):
        if not p.is_file() or "packaging-033" in p.relative_to(ev).parts or p.name == "RUN_SHA256SUMS.json":
            continue
        if any(d == p.parent or d in p.parents for d in sealed_dirs):
            continue  # covered by its run seal
        add("evidence-file", p)
    OUT.write_text("".join(f"{d}  {k}  {p}\n" for d, k, p in entries))
    kinds = {}
    for _, k, _ in entries:
        kinds[k] = kinds.get(k, 0) + 1
    report = {"run_seals": len(seals), "sealed_members_rehashed": members, "mismatches": bad, "index": rel(OUT),
              "index_entries": len(entries), "per_kind": kinds, "index_sha256": sha(OUT)}
    print(json.dumps(report, indent=1))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
