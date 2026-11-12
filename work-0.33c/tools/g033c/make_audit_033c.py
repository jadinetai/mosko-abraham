"""ABRAHAM 0.33c compact audit package for Echo (D-ABR-026 Phase 5). Post-campaign tool; not under test.

  python -I -B tools/g033c/make_audit_033c.py      (console goes to evidence/packaging-033c/, NOT packaged)

Writes work-0.33c/evidence/review/ABRAHAM_0.33c_ECHO_AUDIT.zip (+ .sha256). The 0.33 packager
(tools/g033/make_audit_033.py) with the 0.33c inputs. Contents, by their paths under Documents\\Abraham:
  - owner records: DECISIONS.md; the 0.33c and VM-launcher directives; TR-0042, TR-0044, TR-0045, TR-0046 and the 0.33c
    records (TR-0049, TR-0050) when they exist (they do not contain this package's digest); the baseline;
  - the home patch notes 0.33c, the earlier indexes and package digests it builds on;
  - work-0.33c: README, copy manifests, the evidence index, docs, kernel source, tools (with the official judges:
    tools/abr_boot_001.py, tools/g033/launch_probe.py, tools/g032b, tools/g3/compare_sections.py), boot config,
    build-info, and every 0.33c evidence file;
  - the TESTED kernel binaries: every kernel of the 0.33c BUILD_MANIFEST this tree built, taken from the preserved
    work-0.33 copy where Phase 4 replaced it in work-0.33c (both are packaged; the index lists both);
  - the tested launcher programs: vmlauncher-0.33.1/Abraham-VM-Launcher.exe (c09f1cbf, the 0.33.1 reproduction) and the
    whole vmlauncher-0.33.2 tree (source, program, tools, docs, its index and campaign);
  - every sealed run folder WITHOUT its boot-disk members (esp/, vars.fd: Limine binary, kernel copy, firmware
    variables), all pinned by digest in the run seal and listed in OMITTED.json.
The 0.34 First Light proposal is NOT in this package: the owner review gate presents it separately.
MANIFEST.sha256 covers every packaged file. verify_audit_033c.py (inside) checks: the manifest, every seal, every
index entry present in the package, the tested kernels against the BUILD_MANIFEST, and the launcher campaign seal.
The negative-test trees K002/K003/K004 are omitted (rebuilt by the campaign's prepare step). Standard library only.
"""
import hashlib
import json
import zipfile
from pathlib import Path

W = Path(__file__).resolve().parents[2]
HOME = W.parent
OLD = HOME / "work-0.33"
VML2 = HOME / "vmlauncher-0.33.2"
OUT = W / "evidence" / "review" / "ABRAHAM_0.33c_ECHO_AUDIT.zip"
SKIP = {"target", "__pycache__", "hosttest-target", "K002-tree", "K003-tree", "K004-tree", "packaging-033c", "review",
        "mutants-032b", "mutants-033", "repro1", "repro2", "cargo"}

VERIFY = r'''"""Verify an extracted ABRAHAM 0.33c audit package.   python -I -B verify_audit_033c.py <extracted dir>"""
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
idx = {l.split("  ")[2].replace("\\", "/"): l.split("  ")[0] for l in (root / "work-0.33c/EVIDENCE_INDEX_0.33c.sha256").read_text().splitlines()}
checked = 0
for rel, d in idx.items():
    if (root / rel).is_file():
        checked += 1
        if sha(root / rel) != d: bad.append(f"index: {rel}")
bm = json.loads((root / "work-0.33c/evidence/campaign-033c/BUILD_MANIFEST.json").read_text())
kernels = 0
for k, v in bm["kernels"].items():
    p = Path(v["path"])
    if p.is_absolute():
        continue  # a pinned reference kernel of an earlier tree, carried by that tree's own package
    kernels += 1
    here, tested = root / "work-0.33c" / p, root / "work-0.33" / p
    if not ((here.is_file() and sha(here) == v["sha256"]) or (tested.is_file() and sha(tested) == v["sha256"])):
        bad.append(f"kernel {k} ({v['path']})")
camp = root / "vmlauncher-0.33.2/evidence/campaign-vml/CAMPAIGN_SHA256SUMS.json"
camp_n = 0
if camp.is_file():
    for name, d in json.loads(camp.read_text()).items():
        camp_n += 1
        f = camp.parent / name
        if f.is_file():
            if sha(f) != d: bad.append(f"launcher campaign: {name}")
        elif omitted.get(f"vmlauncher-0.33.2/evidence/campaign-vml/{name}") != d:
            bad.append(f"launcher campaign: {name} (missing, not listed as omitted)")
else:
    bad.append("vmlauncher-0.33.2 campaign seal missing")
exe = {t: sha(root / t / "Abraham-VM-Launcher.exe") for t in ("vmlauncher-0.33.1", "vmlauncher-0.33.2") if (root / t / "Abraham-VM-Launcher.exe").is_file()}
print(json.dumps({"manifest_entries": n, "run_seals": seals, "sealed_members_rehashed": rehashed,
                  "sealed_members_omitted_and_listed": omit_ok, "index_entries": len(idx),
                  "index_entries_present_and_checked": checked, "kernel_binaries_checked": kernels,
                  "production_kernel_sha256": bm["kernels"]["default"]["sha256"], "launcher_campaign_members": camp_n,
                  "launcher_programs": exe, "mismatches": bad}, indent=1))
print("AUDIT ARCHIVE VERIFIED" if not bad else "AUDIT ARCHIVE DISCREPANCY")
sys.exit(0 if not bad else 1)
'''


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def tree(d, base=None):
    base = base or d
    return [p for p in sorted(d.rglob("*")) if p.is_file() and not (SKIP & set(p.relative_to(base).parts))
            and p.suffix != ".zip"]


def main():
    if OUT.exists():
        raise SystemExit(f"REFUSED: {OUT} exists")
    files = [HOME / n for n in ("DECISIONS.md", "ABRAHAM_0.2_BASELINE.md", "MOSKO_ABRAHAM_033C_FINAL_AUDIT_DIRECTIVE_2026-11-10.md",
                                "MOSKO_ABRAHAM_033_VM_LAUNCHER_DIRECTIVE_2026-11-09.md", "PATCH_NOTES_0.33c.md")]
    files += [HOME / "test-records" / f"{tr}.md" for tr in ("TR-0042", "TR-0044", "TR-0045", "TR-0046", "TR-0049", "TR-0050")
              if (HOME / "test-records" / f"{tr}.md").is_file()]
    files += [OLD / "EVIDENCE_INDEX_0.33.sha256", OLD / "evidence" / "review" / "ABRAHAM_0.33_ECHO_AUDIT.zip.sha256",
              HOME / "vmlauncher-0.33" / "EVIDENCE_INDEX_VML_0.33.sha256",
              HOME / "vmlauncher-0.33.1" / "EVIDENCE_INDEX_VML_0.33.1.sha256",
              HOME / "vmlauncher-0.33.1" / "evidence" / "review" / "ABRAHAM_0.33.1_VM_LAUNCHER_AUDIT.zip.sha256",
              HOME / "vmlauncher-0.33.1" / "Abraham-VM-Launcher.exe",
              W / "README.md", W / "COPY_MANIFEST_FROM_0.33.json", W / "COPY_MANIFEST_FROM_0.32b.json",
              W / "EVIDENCE_INDEX_0.33c.sha256",
              W / "build" / "build-info.json", *sorted((W / "build" / "diag").glob("build-info-*.json"))]
    bm = json.loads((W / "evidence" / "campaign-033c" / "BUILD_MANIFEST.json").read_text())
    for v in bm["kernels"].values():
        if Path(v["path"]).is_absolute():
            continue
        here = W / v["path"]
        files.append(here)
        if sha_b(here.read_bytes()) != v["sha256"]:
            files.append(OLD / v["path"])  # the tested binary, preserved in work-0.33
    for d in ("docs", "kernel", "tools", "boot"):
        files += tree(W / d, W)
    # Boot-disk members (esp/..., vars.fd) of every sealed run are omitted and listed with their sealed digest; a
    # boot-disk file no run seal lists is packaged.
    omitted = {}
    for base in (W / "evidence", VML2):
        for s in sorted(base.rglob("RUN_SHA256SUMS.json")):
            if SKIP & set(s.relative_to(base).parts):
                continue
            for name, digest in json.loads(s.read_text()).items():
                if name.startswith("esp/") or name == "vars.fd":
                    omitted[(s.parent / name).relative_to(HOME).as_posix()] = digest
    files += [p for p in tree(W / "evidence", W) if p.relative_to(HOME).as_posix() not in omitted]
    # the launcher 0.33.2 tree: everything but build output and evidence/review. Its runs/ folder holds the operator's
    # own launches (made before the package; TR-0050) and is packaged with them.
    files += [p for p in tree(VML2) if p.relative_to(HOME).as_posix() not in omitted]
    files = sorted(set(files))
    manifest = []
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            data = p.read_bytes()
            arc = p.relative_to(HOME).as_posix()
            z.writestr(zipfile.ZipInfo(arc, date_time=(2026, 11, 10, 0, 0, 0)), data, zipfile.ZIP_DEFLATED)
            manifest.append(f"{sha_b(data)}  {arc}")
        for arc, text in (("OMITTED.json", json.dumps(omitted, indent=1, sort_keys=True) + "\n"), ("verify_audit_033c.py", VERIFY)):
            z.writestr(zipfile.ZipInfo(arc, date_time=(2026, 11, 10, 0, 0, 0)), text, zipfile.ZIP_DEFLATED)
            manifest.append(f"{sha_b(text.encode())}  {arc}")
        z.writestr(zipfile.ZipInfo("MANIFEST.sha256", date_time=(2026, 11, 10, 0, 0, 0)), "\n".join(manifest) + "\n", zipfile.ZIP_DEFLATED)
    digest = sha_b(OUT.read_bytes())
    (OUT.parent / (OUT.name + ".sha256")).write_text(f"{digest}  {OUT.name}\n")
    print(json.dumps({"zip": str(OUT.relative_to(HOME)), "sha256": digest, "bytes": OUT.stat().st_size,
                      "files": len(manifest) + 1, "omitted_boot_disk_members": len(omitted)}, indent=1))


if __name__ == "__main__":
    main()
