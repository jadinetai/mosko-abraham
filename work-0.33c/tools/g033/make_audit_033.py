"""ABRAHAM 0.33 compact audit package for Echo (directive Phase 5), written after `campaign close`.

  python -I -B tools/g033/make_audit_033.py      (console goes to evidence/packaging-033/, NOT packaged)

Writes work-0.33/evidence/review/ABRAHAM_0.33_ECHO_AUDIT.zip (+ .sha256). The 0.32b packager
(tools/g032b/make_audit_032b.py) with one lesson of the 0.32b acceptance gate (TR-0039) applied: the package
CONTAINS the kernel binaries this tree built (the production kernel and every DIAGNOSTIC build of the campaign
BUILD_MANIFEST), so the tested binary can be hashed independently. Contents, by their paths under Documents\\Abraham:
  - owner records (DECISIONS.md; TR-0039, TR-0040, TR-0041 and, when it exists, the 0.33 record TR-0042, which does
    not contain this package's digest), the 0.33 preparation directive, Echo's 0.32b final review, the 0.32b
    directive;
  - the ratified baseline (C12, C13 and the reason checker parse Appendix A from it);
  - the earlier indexes it builds on and the 0.32b package digests;
  - the 0.33 documents (design, addendum, patch notes, operator checklist, KERNEL_DIAGNOSTICS) and the source diff
    from accepted 0.32b;
  - every 0.33 source and tool, build-info, the kernel binaries, the campaign files and the evidence index;
  - the Step 1 runs, the development runs, and every sealed 0.33 run folder WITHOUT its boot-disk members (esp/,
    vars.fd: Limine binary, kernel copy, firmware variables), all pinned by digest in the run seal and listed in
    OMITTED.json.
MANIFEST.sha256 covers every packaged file. verify_audit_033.py (inside) checks it all: the manifest, every seal,
every index entry present in the package, and every non-reference kernel binary against the BUILD_MANIFEST. The
negative-test trees K002/K003/K004 are omitted (indexed; rebuilt by the campaign's prepare step). This tool's
console is never written into a folder it packages. Standard library only.
"""
import hashlib
import json
import zipfile
from pathlib import Path

W = Path(__file__).resolve().parents[2]
HOME = W.parent
OUT = W / "evidence" / "review" / "ABRAHAM_0.33_ECHO_AUDIT.zip"
SKIP = {"target", "__pycache__", "K002-tree", "K003-tree", "K004-tree", "packaging-033"}

VERIFY = r'''"""Verify an extracted ABRAHAM 0.33 audit package.   python -I -B verify_audit_033.py <extracted dir>"""
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
bad, n = [], 0
for line in (root / "MANIFEST.sha256").read_text().splitlines():
    d, rel = line.split("  ", 1); n += 1
    if not (root / rel).is_file() or sha(root / rel) != d: bad.append(rel)
omitted = json.loads((root / "OMITTED.json").read_text())
seals = rehashed = omit_ok = 0
for s in sorted(root.rglob("RUN_SHA256SUMS.json")):
    seals += 1
    run = s.parent.relative_to(root).as_posix()
    for name, d in json.loads(s.read_text()).items():
        f = s.parent / name
        if f.is_file():
            rehashed += 1
            if sha(f) != d: bad.append(f"{run}/{name}")
        elif omitted.get(f"{run}/{name}") == d: omit_ok += 1
        else: bad.append(f"{run}/{name} (missing, not listed as omitted)")
idx = {l.split("  ")[2].replace("\\", "/"): l.split("  ")[0] for l in (root / "work-0.33/EVIDENCE_INDEX_0.33.sha256").read_text().splitlines()}
checked = 0
for rel, d in idx.items():
    if (root / rel).is_file():
        checked += 1
        if sha(root / rel) != d: bad.append(f"index: {rel}")
bm = json.loads((root / "work-0.33/evidence/campaign-033/BUILD_MANIFEST.json").read_text())
kernels = 0
for k, v in bm["kernels"].items():
    p = Path(v["path"])
    if p.is_absolute():
        continue  # a pinned reference kernel of an earlier tree, carried by that tree's own package
    f = root / "work-0.33" / p
    kernels += 1
    if not f.is_file() or sha(f) != v["sha256"]: bad.append(f"kernel {k} ({v['path']})")
print(json.dumps({"manifest_entries": n, "run_seals": seals, "sealed_members_rehashed": rehashed,
                  "sealed_members_omitted_and_listed": omit_ok, "index_entries": len(idx),
                  "index_entries_present_and_checked": checked, "kernel_binaries_checked": kernels,
                  "production_kernel_sha256": bm["kernels"]["default"]["sha256"], "mismatches": bad}, indent=1))
print("AUDIT ARCHIVE VERIFIED" if not bad else "AUDIT ARCHIVE DISCREPANCY")
sys.exit(0 if not bad else 1)
'''


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if OUT.exists():
        raise SystemExit(f"REFUSED: {OUT} exists")
    files = [HOME / n for n in ("DECISIONS.md", "ABRAHAM_0.2_BASELINE.md", "MOSKO_ABRAHAM_033_PREPARATION_DIRECTIVE_2026-11-08.md",
                                "MOSKO_ABRAHAM_032B_ECHO_FINAL_AUDIT_2026-11-08.md", "MOSKO_ABRAHAM_032B_CORRECTIVE_DIRECTIVE_2026-11-08.md",
                                "ABRAHAM_0.33_DESIGN.md")]
    files += [HOME / "test-records" / f"{tr}.md" for tr in ("TR-0039", "TR-0040", "TR-0041", "TR-0042")
              if (HOME / "test-records" / f"{tr}.md").is_file()]
    files += [HOME / "test-records" / "TR-0040.verify.out.txt",
              HOME / "work-0.32b" / "EVIDENCE_INDEX_0.32b.sha256",
              HOME / "work-0.32b" / "evidence" / "review" / "ABRAHAM_0.32b_ECHO_AUDIT.zip.sha256",
              HOME / "gate-0.32b" / "GATE_EVIDENCE_INDEX_0.32b.sha256",
              HOME / "gate-0.32b" / "review" / "ABRAHAM_0.32b_FINAL_AUDIT.zip.sha256",
              HOME / "work-0.32" / "EVIDENCE_INDEX_0.32.sha256",
              HOME / "frozen" / "ABR-BOOT-001-accepted" / "FREEZE_MANIFEST.sha256",
              HOME / "work-0.29" / "EVIDENCE_INDEX_0.29_SIGNOFF.sha256",
              HOME / "work-0.31" / "EVIDENCE_INDEX_0.31a.sha256",
              HOME / "work-0.31b" / "EVIDENCE_INDEX_0.31b.sha256",
              W / "README.md", W / "COPY_MANIFEST_FROM_0.32b.json", W / "EVIDENCE_INDEX_0.33.sha256",
              W / "build" / "build-info.json", *sorted((W / "build" / "diag").glob("build-info-*.json"))]
    bm = json.loads((W / "evidence" / "campaign-033" / "BUILD_MANIFEST.json").read_text())
    files += [W / v["path"] for v in bm["kernels"].values() if not Path(v["path"]).is_absolute()]
    for d in ("docs", "kernel", "tools", "boot", "evidence/review", "evidence/campaign-033"):
        files += [p for p in sorted((W / d).rglob("*")) if p.is_file() and not (SKIP & set(p.relative_to(W).parts))
                  and p != OUT and p.suffix != ".zip"]
    omitted = {}
    for s in sorted((W / "evidence").rglob("RUN_SHA256SUMS.json")):
        for name, digest in json.loads(s.read_text()).items():
            if name.startswith("esp/") or name == "vars.fd":
                omitted[(s.parent / name).relative_to(HOME).as_posix()] = digest
            else:
                files.append(s.parent / name)
        files.append(s)
    files = sorted(set(files))
    manifest = []
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            data = p.read_bytes()
            arc = p.relative_to(HOME).as_posix()
            z.writestr(arc, data)
            manifest.append(f"{sha_b(data)}  {arc}")
        for arc, text in (("OMITTED.json", json.dumps(omitted, indent=1, sort_keys=True) + "\n"), ("verify_audit_033.py", VERIFY)):
            z.writestr(arc, text)
            manifest.append(f"{sha_b(text.encode())}  {arc}")
        z.writestr("MANIFEST.sha256", "\n".join(manifest) + "\n")
    digest = sha_b(OUT.read_bytes())
    (OUT.parent / (OUT.name + ".sha256")).write_text(f"{digest}  {OUT.name}\n")
    print(json.dumps({"zip": str(OUT.relative_to(HOME)), "sha256": digest, "bytes": OUT.stat().st_size,
                      "files": len(manifest) + 1, "omitted_boot_disk_members": len(omitted)}, indent=1))


if __name__ == "__main__":
    main()
