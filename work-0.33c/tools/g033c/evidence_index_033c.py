"""ABRAHAM 0.33c evidence index and seal re-verification (D-ABR-026 Phase 5). Post-campaign tool; not under test.

  python -I -B tools/g033c/evidence_index_033c.py

The 0.33 index tool (tools/g033/evidence_index_033.py) with the 0.33c inputs.
1. Re-hashes every member of every RUN_SHA256SUMS.json under work-0.33c/evidence (any depth).
2. Checks every kernel of the 0.33c campaign BUILD_MANIFEST. Phase 4 rebuilt two DIAGNOSTIC builds in place
   (build/diag launchpad and early-fail: work-0.33c-path builds, loaded sections identical to the tested binaries,
   evidence/phase4/ABR-0.33c-P4). For such a kernel the TESTED binary is the preserved work-0.33 file at the same
   relative path; it must match the manifest, and the replacement is listed, never hidden.
3. Writes work-0.33c/EVIDENCE_INDEX_0.33c.sha256 ("<sha256>  <kind>  <path from Documents\\Abraham>"):
   - the directives, DECISIONS.md, the baseline;
   - the earlier indexes and package digests it builds on (0.33 and the launchers 0.33, 0.33.1, 0.33.2);
   - the records TR-0042, TR-0044, TR-0045, TR-0046;
   - documents, kernel sources, tools, boot config, the copy manifest;
   - kernel binaries (tested; and the Phase 4 replacements), build-info;
   - every run seal, and every evidence file NOT covered by a run seal.
   evidence/review/ and evidence/packaging-033c/ (written after this index) are excluded. Refuses to overwrite. The
   0.33c records (TR-0049, TR-0050) and test-records/INDEX.md are not in it: the records cite this index's digest.
Standard library only.
"""
import hashlib
import json
import sys
from pathlib import Path

W = Path(__file__).resolve().parents[2]
HOME = W.parent
OLD = HOME / "work-0.33"
OUT = W / "EVIDENCE_INDEX_0.33c.sha256"
SKIP = {"target", "__pycache__", "hosttest-target", "K002-tree", "K003-tree", "K004-tree"}
EXCLUDE_EVIDENCE = {"review", "packaging-033c"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rel(p):
    return str(Path(p).resolve().relative_to(HOME))


def main():
    if OUT.exists():
        raise SystemExit(f"REFUSED: {OUT} exists")
    ev = W / "evidence"
    seals = sorted(s for s in ev.rglob("RUN_SHA256SUMS.json") if not (EXCLUDE_EVIDENCE & set(s.relative_to(ev).parts)))
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
    for name in ("MOSKO_ABRAHAM_033C_FINAL_AUDIT_DIRECTIVE_2026-11-10.md", "MOSKO_ABRAHAM_033_VM_LAUNCHER_DIRECTIVE_2026-11-09.md",
                 "MOSKO_ABRAHAM_033_PREPARATION_DIRECTIVE_2026-11-08.md"):
        add("directive", HOME / name)
    add("decisions", HOME / "DECISIONS.md")
    add("baseline", HOME / "ABRAHAM_0.2_BASELINE.md")
    add("evidence-index-0.33", OLD / "EVIDENCE_INDEX_0.33.sha256")
    add("audit-zip-0.33", OLD / "evidence" / "review" / "ABRAHAM_0.33_ECHO_AUDIT.zip.sha256")
    for tree, idx in (("vmlauncher-0.33", "EVIDENCE_INDEX_VML_0.33.sha256"), ("vmlauncher-0.33.1", "EVIDENCE_INDEX_VML_0.33.1.sha256"),
                      ("vmlauncher-0.33.2", "EVIDENCE_INDEX_VML_0.33.2.sha256")):
        add(f"launcher-index-{tree[11:]}", HOME / tree / idx)
    for tree, z in (("vmlauncher-0.33", "ABRAHAM_0.33_VM_LAUNCHER_AUDIT.zip"), ("vmlauncher-0.33.1", "ABRAHAM_0.33.1_VM_LAUNCHER_AUDIT.zip")):
        add(f"launcher-zip-{tree[11:]}", HOME / tree / "evidence" / "review" / (z + ".sha256"))
    for tr in ("TR-0042", "TR-0044", "TR-0045", "TR-0046"):
        add("record", HOME / "test-records" / f"{tr}.md")
    for p in [W / "README.md", W / "COPY_MANIFEST_FROM_0.33.json", W / "COPY_MANIFEST_FROM_0.32b.json", *sorted((W / "docs").glob("*.md"))]:
        add("document", p)
    for d, kind in (("kernel", "kernel-source"), ("tools", "tool"), ("boot", "boot-config")):
        for p in sorted((W / d).rglob("*")):
            if p.is_file() and not (SKIP & set(p.relative_to(W).parts)):
                add(kind, p)
    manifest = json.loads((ev / "campaign-033c" / "BUILD_MANIFEST.json").read_text())
    replaced = []
    for k, v in manifest["kernels"].items():
        p = Path(v["path"]) if Path(v["path"]).is_absolute() else W / v["path"]
        if sha(p) == v["sha256"]:
            add("kernel-binary", p)
            continue
        tested = OLD / v["path"]
        if Path(v["path"]).is_absolute() or not tested.is_file() or sha(tested) != v["sha256"]:
            bad.append(f"kernel {k} differs from BUILD_MANIFEST and no preserved tested copy matches")
            continue
        add("kernel-binary-tested", tested)
        add("kernel-binary-phase4-rebuild", p)
        replaced.append({"kernel": k, "path": v["path"], "tested_sha256": v["sha256"], "work_0_33c_now": sha(p),
                         "tested_copy": rel(tested)})
    for p in [W / "build" / "build-info.json", *sorted((W / "build" / "diag").glob("build-info-*.json"))]:
        add("build-info", p)
    for s in seals:
        add("run-seal", s)
    for p in sorted(ev.rglob("*")):
        parts = set(p.relative_to(ev).parts)
        if not p.is_file() or (EXCLUDE_EVIDENCE & parts) or (SKIP & parts) or p.name == "RUN_SHA256SUMS.json":
            continue
        if any(d == p.parent or d in p.parents for d in sealed_dirs):
            continue  # covered by its run seal
        add("evidence-file", p)
    OUT.write_text("".join(f"{d}  {k}  {p}\n" for d, k, p in entries))
    kinds = {}
    for _, k, _ in entries:
        kinds[k] = kinds.get(k, 0) + 1
    report = {"run_seals": len(seals), "sealed_members_rehashed": members, "mismatches": bad,
              "kernels_replaced_in_work_0_33c_by_phase4": replaced, "index": rel(OUT),
              "index_entries": len(entries), "per_kind": kinds, "index_sha256": sha(OUT)}
    print(json.dumps(report, indent=1))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
