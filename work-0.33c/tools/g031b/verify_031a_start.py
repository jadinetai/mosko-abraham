"""ABRAHAM 0.31b Step 1: verify the exact 0.31a starting state (read-only; writes only its report).

  python -I -B tools/g031b/verify_031a_start.py <report.json> <checkpoint.sha256>

Checks, against what 0.31a recorded (TR-0033):
  1. EVIDENCE_INDEX_0.31a.sha256 digest, then every entry (append-only DECISIONS.md / INDEX.md as
     whole-line prefixes);
  2. every RUN_SHA256SUMS.json under work-0.31/evidence, every member (including the boot-disk
     members omitted from the compact Echo package);
  3. BUILD_MANIFEST.json kernels; the 0.31a kernel = b9a8f8f9...;
  4. kernel/, tools/, boot/ now vs SOURCE_MANIFEST_END.json (post-campaign additions listed);
  5. the audit zip and its .sha256; which packaged files differ from disk now;
  6. campaign.json (31 runs, all as expected); TR-0033 and its INDEX row; D-ABR-009..013 rows;
     the four 2026-11-05 directive documents; Limine binary and limine.conf in work-0.31.
Writes a full-tree checkpoint of work-0.31 (every file) so 0.31b can prove at the end that the
0.31a tree was not changed. Never writes into work-0.31. Standard library only.
"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
W31 = HOME / "work-0.31"
INDEX = W31 / "EVIDENCE_INDEX_0.31a.sha256"
INDEX_SHA = "16f02153670879c68fb20a0f720df2296f7f9cf067a1e5c94b29d4ce120642e6"
ZIP = W31 / "evidence" / "review" / "ABRAHAM_0.31a_ECHO_AUDIT.zip"
ZIP_SHA = "32ffc29107cb5198d4f117f121f18bd1ab07006cde99316c48bca2d5dae3f80b"
KERNEL_031A = "b9a8f8f9ed8b5f916e280a060a456c9849a510ec6566261639b91b896838aa76"
LIMINE = "e486ae7abd7d5b88f98f43cfd6e8f9057ff975ecd667dfb33f1581de36e00982"
APPEND_ONLY = {"DECISIONS.md", "test-records\\INDEX.md"}
SKIP = {"target", "__pycache__"}


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def sha(p):
    return sha_b(Path(p).read_bytes())


def prefix_ok(p, digest):
    data = p.read_bytes()
    if sha_b(data) == digest:
        return "EXACT"
    i = 0
    while (i := data.find(b"\n", i)) >= 0:
        i += 1
        if sha_b(data[:i]) == digest:
            return f"PREFIX({i} of {len(data)} bytes)"
    return None


out = {"checks": {}, "notes": [], "fail": []}


def check(name, ok, detail):
    out["checks"][name] = {"ok": bool(ok), "detail": detail}
    if not ok:
        out["fail"].append(name)


# 1. evidence index
check("index.digest", sha(INDEX) == INDEX_SHA, sha(INDEX))
mism, prefixes, n = [], {}, 0
for line in INDEX.read_text().splitlines():
    d, kind, rel = line.split("  ")
    n += 1
    p = HOME / rel
    if not p.is_file():
        mism.append({"path": rel, "kind": kind, "problem": "missing"})
    elif rel in APPEND_ONLY:
        prefixes[rel] = prefix_ok(p, d)
        if not prefixes[rel]:
            mism.append({"path": rel, "kind": kind, "problem": "not an append-only extension"})
    elif sha(p) != d:
        mism.append({"path": rel, "kind": kind, "problem": "content differs from the index", "now": sha(p)})
check("index.entries", not [m for m in mism if m["kind"] != "document"],
      {"entries": n, "append_only": prefixes, "mismatches": mism,
       "rule": "only 'document' entries may differ (post-index documentation edits), and each must be explained"})

# 2. seals
seals, members, bad, omitted_ok = 0, 0, [], 0
zip_names = set(zipfile.ZipFile(ZIP).namelist())
for s in sorted((W31 / "evidence").rglob("RUN_SHA256SUMS.json")):
    seals += 1
    for name, d in json.loads(s.read_text()).items():
        members += 1
        f = s.parent / name
        if not f.is_file() or sha(f) != d:
            bad.append(str(f.relative_to(HOME)))
        elif f.relative_to(HOME).as_posix() not in zip_names:
            omitted_ok += 1
check("seals.all_members_on_disk", not bad and seals == 29 and members == 402,
      {"run_seals": seals, "members": members, "mismatches": bad,
       "members_absent_from_echo_zip_but_verified_here": omitted_ok})

# 3. builds
bm = json.loads((W31 / "evidence" / "campaign-031a" / "BUILD_MANIFEST.json").read_text())
kb = {}
for k, v in bm["kernels"].items():
    p = Path(v["path"]) if Path(v["path"]).is_absolute() else W31 / v["path"]
    kb[k] = p.is_file() and sha(p) == v["sha256"]
check("builds.manifest_kernels", all(kb.values()), kb)
check("builds.kernel_031a", sha(W31 / "build" / "abraham-kernel-0.31.0-dev.elf") == KERNEL_031A,
      sha(W31 / "build" / "abraham-kernel-0.31.0-dev.elf"))

# 4. source drift since the campaign closed
end = json.loads((W31 / "evidence" / "campaign-031a" / "SOURCE_MANIFEST_END.json").read_text())
now = {}
for d in ("kernel", "tools", "boot"):
    for p in sorted((W31 / d).rglob("*")):
        if p.is_file() and not (SKIP & set(p.relative_to(W31).parts)):
            now[p.relative_to(W31).as_posix()] = sha(p)
changed = sorted(k for k in end if k in now and now[k] != end[k])
removed = sorted(set(end) - set(now))
added = sorted(set(now) - set(end))
expected_added = {"tools/g031/source_diff.py", "tools/g031/evidence_index.py", "tools/g031/make_audit_031a.py"}
check("source.unchanged_since_campaign", not changed and not removed and set(added) == expected_added,
      {"changed": changed, "removed": removed, "added_after_close": added,
       "expected_added_after_close (TR-0033 deviation 3)": sorted(expected_added)})

# 5. audit zip
zs = (ZIP.parent / (ZIP.name + ".sha256")).read_text().split()[0]
check("zip.digest", sha(ZIP) == ZIP_SHA and zs == ZIP_SHA, {"zip": sha(ZIP), "sha256_file": zs})
zdiff = []
with zipfile.ZipFile(ZIP) as z:
    for name in z.namelist():
        disk = HOME / name
        if disk.is_file() and sha_b(z.read(name)) != sha(disk):
            zdiff.append(name)
out["zip_members_differing_from_disk_now"] = zdiff

# 6. records, decisions, directives, configuration
camp = json.loads((W31 / "evidence" / "campaign-031a" / "campaign.json").read_text())
check("campaign.31_as_expected", len(camp["runs"]) == 31 and camp.get("all_as_expected") is True
      and camp.get("source_changed_during_campaign") == [], {"runs": len(camp["runs"])})
tr = HOME / "test-records" / "TR-0033.md"
idx = (HOME / "test-records" / "INDEX.md").read_text(encoding="utf-8")
check("records.tr0033", tr.is_file() and "| TR-0033 |" in idx, {"tr0033_sha256": sha(tr)})
dec = (HOME / "DECISIONS.md").read_text(encoding="utf-8")
rows = {f"D-ABR-{i:03d}": f"| D-ABR-{i:03d} |" in dec for i in range(9, 14)}
check("decisions.d009_d013", all(rows.values()), {"rows": rows, "decisions_sha256": sha(HOME / "DECISIONS.md")})
docs = {}
for name in ("MOSKO_ABRAHAM_029_ECHO_INDEPENDENT_AUDIT_2026-11-05.md", "MOSKO_ABRAHAM_NEW_CLAUDE_THREAD_HANDOFF_2026-11-05.md",
             "MOSKO_ABRAHAM_031A_ECHO_AUDIT_2026-11-05.md", "MOSKO_ABRAHAM_031B_DEVELOPMENT_DIRECTIVE_2026-11-05.md"):
    docs[name] = sha(HOME / name) if (HOME / name).is_file() else None
check("directives.present", all(docs.values()), docs)
efi = W31 / "third_party" / "limine-12.9.6" / "extracted" / "limine-binary" / "BOOTX64.EFI"
check("config.limine_efi", sha(efi) == LIMINE, sha(efi))
out["config_limine_conf_sha256"] = sha(W31 / "boot" / "limine.conf")

# checkpoint of the whole 0.31a tree
cp = Path(sys.argv[2])
lines = [f"{sha(p)}  {p.relative_to(HOME)}" for p in sorted(W31.rglob("*")) if p.is_file()]
cp.write_text("\n".join(lines) + "\n")
out["checkpoint"] = {"path": str(cp), "files": len(lines), "sha256": sha(cp)}

out["verdict"] = "0.31a STARTING STATE VERIFIED" if not out["fail"] else "0.31a STARTING STATE DISCREPANCY"
Path(sys.argv[1]).write_text(json.dumps(out, indent=1) + "\n")
print(out["verdict"], "fail:", out["fail"])
for k, v in out["checks"].items():
    print(("OK  " if v["ok"] else "FAIL"), k)
print("index mismatches:", json.dumps(out["checks"]["index.entries"]["detail"]["mismatches"], indent=1))
print("zip members differing from disk now:", zdiff)
print("checkpoint:", out["checkpoint"])
sys.exit(0 if not out["fail"] else 1)
