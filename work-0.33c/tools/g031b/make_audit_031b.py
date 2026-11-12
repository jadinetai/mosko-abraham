"""ABRAHAM 0.31b: compact audit package for Echo (directive Step 6).

  python -I -B tools/g031b/make_audit_031b.py      (console goes to evidence/packaging/, NOT packaged)

Writes work-0.31b/evidence/review/ABRAHAM_0.31b_ECHO_AUDIT.zip (+ .sha256). Contents, by their paths under
Documents\\Abraham: owner records, the four directives and Echo's 0.31a audit, the 0.29/0.31a indexes it builds
on, the 0.31b documents and both source diffs, every 0.31b source and tool, build-info, the campaign files, the
evidence index, the Step 1 verification and checkpoint, investigation and development checks, and every sealed
0.31b run folder WITHOUT its boot-disk members (esp/, vars.fd: Limine binary, kernel copy, firmware variables,
all pinned by digest in the run seal; listed in OMITTED.json). MANIFEST.sha256 covers every packaged file;
verify_audit_031b.py (inside) checks it all, including every index entry present in the package.
0.31a lesson (TR-0033 deviation 4): this tool's console is never written into a folder it packages.
Standard library only.
"""
import hashlib
import json
import zipfile
from pathlib import Path

W = Path(__file__).resolve().parents[2]
HOME = W.parent
OUT = W / "evidence" / "review" / "ABRAHAM_0.31b_ECHO_AUDIT.zip"
SKIP = {"target", "__pycache__", "K002-tree", "packaging"}

VERIFY = r'''"""Verify an extracted ABRAHAM 0.31b audit package.   python -I -B verify_audit_031b.py <extracted dir>"""
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
idx = {l.split("  ")[2].replace("\\", "/"): l.split("  ")[0] for l in (root / "work-0.31b/EVIDENCE_INDEX_0.31b.sha256").read_text().splitlines()}
checked = 0
for rel, d in idx.items():
    if (root / rel).is_file():
        checked += 1
        if sha(root / rel) != d: bad.append(f"index: {rel}")
print(json.dumps({"manifest_entries": n, "run_seals": seals, "sealed_members_rehashed": rehashed,
                  "sealed_members_omitted_and_listed": omit_ok, "index_entries": len(idx),
                  "index_entries_present_and_checked": checked, "mismatches": bad}, indent=1))
print("AUDIT ARCHIVE VERIFIED" if not bad else "AUDIT ARCHIVE DISCREPANCY")
sys.exit(0 if not bad else 1)
'''


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def main():
    if OUT.exists():
        raise SystemExit(f"REFUSED: {OUT} exists")
    files = [HOME / n for n in ("DECISIONS.md", "MOSKO_ABRAHAM_029_ECHO_INDEPENDENT_AUDIT_2026-11-05.md",
                                "MOSKO_ABRAHAM_NEW_CLAUDE_THREAD_HANDOFF_2026-11-05.md",
                                "MOSKO_ABRAHAM_031A_ECHO_AUDIT_2026-11-05.md",
                                "MOSKO_ABRAHAM_031B_DEVELOPMENT_DIRECTIVE_2026-11-05.md")]
    files += [HOME / "frozen" / "ABR-BOOT-001-accepted" / "FREEZE_MANIFEST.sha256",
              HOME / "work-0.29" / "EVIDENCE_INDEX_0.29_SIGNOFF.sha256",
              HOME / "work-0.31" / "EVIDENCE_INDEX_0.31a.sha256",
              HOME / "work-0.31" / "evidence" / "review" / "ABRAHAM_0.31a_ECHO_AUDIT.zip.sha256",
              W / "README.md", W / "COPY_MANIFEST_FROM_0.31a.json", W / "EVIDENCE_INDEX_0.31b.sha256",
              W / "build" / "build-info.json", *sorted((W / "build" / "diag").glob("build-info-*.json"))]
    for d in ("docs", "kernel", "tools", "boot", "evidence/review", "evidence/campaign-031b", "evidence/start", "evidence/g031b/dev"):
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
        for arc, text in (("OMITTED.json", json.dumps(omitted, indent=1, sort_keys=True) + "\n"), ("verify_audit_031b.py", VERIFY)):
            z.writestr(arc, text)
            manifest.append(f"{sha_b(text.encode())}  {arc}")
        z.writestr("MANIFEST.sha256", "\n".join(manifest) + "\n")
    digest = sha_b(OUT.read_bytes())
    (OUT.parent / (OUT.name + ".sha256")).write_text(f"{digest}  {OUT.name}\n")
    print(json.dumps({"zip": str(OUT.relative_to(HOME)), "sha256": digest, "bytes": OUT.stat().st_size,
                      "files": len(manifest) + 1, "omitted_boot_disk_members": len(omitted)}, indent=1))


if __name__ == "__main__":
    main()
