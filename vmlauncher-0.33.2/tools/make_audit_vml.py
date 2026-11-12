"""ABRAHAM VM LAUNCHER 0.33.2 (0.33c: packaged instead by work-0.33c/tools/g033c/make_audit_033c.py): the audit package for Echo (D-ABR-024 criterion E). Post-campaign tool; not under test.

  python -I -B tools/make_audit_vml.py build <out.zip>
  python -I -B tools/make_audit_vml.py verify <folder where the zip was extracted>

build   writes a zip of the launcher tree (source, program, docs, tools, the counted campaign and its runs, the
        development runs) and of the records it rests on (the directive, DECISIONS.md, the report, the home copy
        of the patch notes, TR-0044, the tree's evidence index). PACKAGE_SHA256SUMS.json inside lists every member's digest. Its own
        digest goes in <out.zip>.sha256 beside it. Build directories (target/) are left out: B001 rebuilds them.
verify  re-hashes every member of an extracted package against PACKAGE_SHA256SUMS.json, re-checks every run seal
        (RUN_SHA256SUMS.json) and the campaign seal inside it, and recomputes the deployed program's digest.
Standard library only.
"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

VML = Path(__file__).resolve().parents[1]
HOME = VML.parent
# The record index (test-records/INDEX.md) is a shared append-only log that gets its TR-0044 row after the package
# exists (the row carries the package digest), so it is not packaged.
EXTRA = ["MOSKO_ABRAHAM_033_VM_LAUNCHER_DIRECTIVE_2026-11-09.md", "MOSKO_ABRAHAM_033C_FINAL_AUDIT_DIRECTIVE_2026-11-10.md",
         "DECISIONS.md", "PATCH_NOTES_0.33c.md", "test-records/TR-0044.md", "test-records/TR-0045.md", "test-records/TR-0046.md"]
SKIP_DIRS = {"target", "__pycache__", "review"}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def members():
    out = []
    for p in sorted(VML.rglob("*")):
        rel = p.relative_to(VML)
        if p.is_file() and not (set(rel.parts[:-1]) & SKIP_DIRS) and rel.parts[0] != "runs":
            out.append((p, "vmlauncher-0.33.2/" + rel.as_posix()))
    for e in EXTRA:
        out.append((HOME / e, e))
    return out


def build(zpath):
    zpath = Path(zpath).resolve()
    sums = {}
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p, name in members():
            data = p.read_bytes()
            sums[name] = sha(data)
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 11, 9, 0, 0, 0)), data, zipfile.ZIP_DEFLATED)
        z.writestr(zipfile.ZipInfo("PACKAGE_SHA256SUMS.json", date_time=(2026, 11, 9, 0, 0, 0)),
                   json.dumps(sums, indent=1, sort_keys=True) + "\n", zipfile.ZIP_DEFLATED)
    digest = sha(zpath.read_bytes())
    zpath.with_name(zpath.name + ".sha256").write_text(f"{digest}  {zpath.name}\n")
    print(json.dumps({"zip": str(zpath), "sha256": digest, "members": len(sums) + 1, "bytes": zpath.stat().st_size}))
    return 0


def verify(root):
    root = Path(root).resolve()
    sums = json.loads((root / "PACKAGE_SHA256SUMS.json").read_text())
    bad = [n for n, d in sums.items() if not (root / n).is_file() or sha((root / n).read_bytes()) != d]
    present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} - {"PACKAGE_SHA256SUMS.json"}
    extra = sorted(present - set(sums))
    seals, seal_bad = 0, []
    for s in sorted(root.rglob("RUN_SHA256SUMS.json")):
        seals += 1
        for n, d in json.loads(s.read_text()).items():
            f = s.parent / n
            if not f.is_file() or sha(f.read_bytes()) != d:
                seal_bad.append(f"{s.parent.relative_to(root).as_posix()}/{n}")
    camp = root / "vmlauncher-0.33.2" / "evidence" / "campaign-vml" / "CAMPAIGN_SHA256SUMS.json"
    camp_bad = [n for n, d in json.loads(camp.read_text()).items()
                if sha((camp.parent / n).read_bytes()) != d] if camp.is_file() else ["CAMPAIGN_SHA256SUMS.json missing"]
    exe = root / "vmlauncher-0.33.2" / "Abraham-VM-Launcher.exe"
    result = {"members_checked": len(sums), "mismatched_or_missing": bad, "unlisted_files": extra,
              "run_seals_checked": seals, "run_seal_mismatches": seal_bad, "campaign_seal_mismatches": camp_bad,
              "program_sha256": sha(exe.read_bytes()) if exe.is_file() else None}
    result["verdict"] = "PACKAGE VERIFIED" if not (bad or extra or seal_bad or camp_bad) else "PACKAGE NOT VERIFIED"
    print(json.dumps(result, indent=1))
    return 0 if result["verdict"] == "PACKAGE VERIFIED" else 1


if __name__ == "__main__":
    mode, arg = sys.argv[1], sys.argv[2]
    sys.exit(build(arg) if mode == "build" else verify(arg))
