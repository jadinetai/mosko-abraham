"""ABRAHAM 0.32 Step 1: verify the exact accepted 0.31b starting state (read-only; writes only its outputs).

  python -I -B tools/g032/verify_031b_start.py <report.json> <checkpoint_work-0.31b.sha256>

Checks, against what 0.31b recorded (TR-0034) and accepted (D-ABR-017, TR-0035):
  1. EVIDENCE_INDEX_0.31b.sha256 digest, then every entry (append-only DECISIONS.md / INDEX.md as whole-line
     prefixes; only 'document' entries may differ, and each one is listed);
  2. every RUN_SHA256SUMS.json under work-0.31b/evidence, every member (53 seals, 1,369 members recorded);
  3. BUILD_MANIFEST.json kernels (14); the accepted kernel = ca847b03... and carries the 0.31.1-dev version string;
  4. kernel/, tools/, boot/ now vs campaign-031b SOURCE_MANIFEST_END.json; the post-close review tools of
     TR-0034 deviation 4 are the only expected differences;
  5. the audit zip and its .sha256 (47f52531...);
  6. campaign.json (52 runs, all as expected, no source change during the campaign);
  7. records: TR-0033..TR-0035 and their INDEX rows; TR-0035.verify.out.txt digest; INDEX's last record is
     TR-0035 (so the next free number is TR-0036);
  8. decisions: D-ABR-001..017 present once each, in order, and D-ABR-017 is the last row (no D-ABR-018 yet);
     D-ABR-017 quotes "Accept 0.31b" and names the accepted kernel, index and zip digests;
  9. the 0.31b directive and the 0.32 handoff are present (digests recorded);
 10. the Limine binary and limine.conf in work-0.31b;
 11. the pinned QEMU 11.1.0 executable digest and its reported version.
Writes a full-tree checkpoint of work-0.31b (every file) so 0.32 can prove at the end that the accepted tree was
not changed. Never writes into work-0.31b. Standard library only.
"""
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
W = HOME / "work-0.31b"
INDEX = W / "EVIDENCE_INDEX_0.31b.sha256"
INDEX_SHA = "81b565fb3b5d9a3bdc375236fec4ada65cd0db0631ae4c06ae047fbd8edafa71"
ZIP = W / "evidence" / "review" / "ABRAHAM_0.31b_ECHO_AUDIT.zip"
ZIP_SHA = "47f52531c132c755fee60a33fb1b13e16cab3a6463f69753ccab5c2afe8fe38f"
KERNEL = W / "build" / "abraham-kernel-0.31.1-dev.elf"
KERNEL_SHA = "ca847b035258bb11258b1867cb9148fed888b2e34e3bf9d1848ad912ea8f1172"
LIMINE = "e486ae7abd7d5b88f98f43cfd6e8f9057ff975ecd667dfb33f1581de36e00982"
TR0035_VERIFY_SHA = "8d9023e857db1a4776f5db447756030d170f5f20ddd1d95a42a76252ba71fb12"
QEMU_DIR = Path(r"C:\Users\XxUnd\abraham-toolchain\qemu\11.1.0-weil-20260811")
QEMU_SHA = "47d57a6072e0bb3bd98f87926eb129eb1736dfe818c67b3b81ef7ce4edd0b3cd"
APPEND_ONLY = {"DECISIONS.md", "test-records\\INDEX.md"}
SKIP = {"target", "__pycache__"}
SEALS, MEMBERS = 53, 1369
# TR-0034 deviation 4: written after `campaign close` (review tools, not code under test).
EXPECTED_CHANGED_AFTER_CLOSE = {"tools/g031/source_diff.py"}
EXPECTED_ADDED_AFTER_CLOSE = {"tools/g031b/evidence_index_031b.py", "tools/g031b/make_audit_031b.py"}


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
mism, prefixes, n, kinds = [], {}, 0, {}
for line in INDEX.read_text().splitlines():
    if not line.strip():
        continue
    d, kind, rel = line.split("  ")
    n += 1
    kinds[kind] = kinds.get(kind, 0) + 1
    p = HOME / rel
    if not p.is_file():
        mism.append({"path": rel, "kind": kind, "problem": "missing"})
    elif rel in APPEND_ONLY:
        prefixes[rel] = prefix_ok(p, d)
        if not prefixes[rel]:
            mism.append({"path": rel, "kind": kind, "problem": "not an append-only extension"})
    elif sha(p) != d:
        mism.append({"path": rel, "kind": kind, "problem": "content differs from the index", "now": sha(p)})
check("index.entries", n == 279 and not [m for m in mism if m["kind"] != "document"],
      {"entries": n, "per_kind": kinds, "append_only": prefixes, "mismatches": mism,
       "rule": "279 entries recorded; only 'document' entries may differ, and each must be explained"})

# 2. seals
seals, members, bad = 0, 0, []
for s in sorted((W / "evidence").rglob("RUN_SHA256SUMS.json")):
    seals += 1
    for name, d in json.loads(s.read_text()).items():
        members += 1
        f = s.parent / name
        if not f.is_file() or sha(f) != d:
            bad.append(str(f.relative_to(HOME)))
check("seals.all_members_on_disk", not bad and seals == SEALS and members == MEMBERS,
      {"run_seals": seals, "members": members, "expected": [SEALS, MEMBERS], "mismatches": bad})

# 3. builds
bm = json.loads((W / "evidence" / "campaign-031b" / "BUILD_MANIFEST.json").read_text())
kb = {}
for k, v in bm["kernels"].items():
    p = Path(v["path"]) if Path(v["path"]).is_absolute() else W / v["path"]
    kb[k] = p.is_file() and sha(p) == v["sha256"]
check("builds.manifest_kernels", len(kb) == 14 and all(kb.values()), kb)
kdata = KERNEL.read_bytes()
check("builds.kernel_031b", sha_b(kdata) == KERNEL_SHA and b"0.31.1-dev" in kdata,
      {"sha256": sha_b(kdata), "version_string_0.31.1-dev": b"0.31.1-dev" in kdata})

# 4. source drift since the campaign closed
end = json.loads((W / "evidence" / "campaign-031b" / "SOURCE_MANIFEST_END.json").read_text())
now = {}
for d in ("kernel", "tools", "boot"):
    for p in sorted((W / d).rglob("*")):
        if p.is_file() and not (SKIP & set(p.relative_to(W).parts)):
            now[p.relative_to(W).as_posix()] = sha(p)
changed = sorted(k for k in end if k in now and now[k] != end[k])
removed = sorted(set(end) - set(now))
added = sorted(set(now) - set(end))
check("source.unchanged_since_campaign",
      set(changed) == EXPECTED_CHANGED_AFTER_CLOSE and not removed and set(added) == EXPECTED_ADDED_AFTER_CLOSE,
      {"manifest_entries": len(end), "changed": changed, "removed": removed, "added_after_close": added,
       "expected (TR-0034 deviation 4)": {"changed": sorted(EXPECTED_CHANGED_AFTER_CLOSE),
                                          "added": sorted(EXPECTED_ADDED_AFTER_CLOSE)}})

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

# 6. campaign
camp = json.loads((W / "evidence" / "campaign-031b" / "campaign.json").read_text())
check("campaign.52_as_expected", len(camp["runs"]) == 52 and camp.get("all_as_expected") is True
      and camp.get("source_changed_during_campaign") == [], {"runs": len(camp["runs"])})

# 7. records
idx = (HOME / "test-records" / "INDEX.md").read_text(encoding="utf-8")
recs = {}
for t in ("TR-0033", "TR-0034", "TR-0035"):
    f = HOME / "test-records" / f"{t}.md"
    recs[t] = {"file": f.is_file(), "index_row": f"| {t} |" in idx, "sha256": sha(f) if f.is_file() else None}
nums = sorted(int(m) for m in re.findall(r"^\| TR-(\d{4}) \|", idx, re.M))
vout = HOME / "test-records" / "TR-0035.verify.out.txt"
check("records.tr0033_tr0035", all(r["file"] and r["index_row"] for r in recs.values())
      and nums[-1] == 35 and sha(vout) == TR0035_VERIFY_SHA,
      {"records": recs, "last_record_in_index": f"TR-{nums[-1]:04d}", "next_free": f"TR-{nums[-1] + 1:04d}",
       "tr0035_verify_out_sha256": sha(vout), "index_sha256": sha(HOME / "test-records" / "INDEX.md")})

# 8. decisions
dec = (HOME / "DECISIONS.md").read_text(encoding="utf-8")
ids = re.findall(r"^\| (D-ABR-\d{3}) \|", dec, re.M)
want = [f"D-ABR-{i:03d}" for i in range(1, 18)]
row17 = next((l for l in dec.splitlines() if l.startswith("| D-ABR-017 |")), "")
check("decisions.d001_d017", ids == want and '"Accept 0.31b"' in row17 and KERNEL_SHA in row17
      and INDEX_SHA in row17 and ZIP_SHA in row17,
      {"rows_in_order": ids, "last": ids[-1] if ids else None, "next_free": f"D-ABR-{len(ids) + 1:03d}",
       "d017_names_kernel_index_zip": [KERNEL_SHA in row17, INDEX_SHA in row17, ZIP_SHA in row17],
       "decisions_sha256": sha(HOME / "DECISIONS.md")})

# 9. directives and handoff
docs = {}
for name in ("MOSKO_ABRAHAM_031B_DEVELOPMENT_DIRECTIVE_2026-11-05.md", "MOSKO_ABRAHAM_032_CLAUDE_HANDOFF_2026-11-05.md",
             "ABRAHAM_0.2_BASELINE.md"):
    docs[name] = sha(HOME / name) if (HOME / name).is_file() else None
check("directives.present", all(docs.values()), docs)
echo = sorted(p.name for p in HOME.glob("*031B*ECHO*")) + sorted(p.name for p in HOME.glob("*0.31b*ECHO*AUDIT*.md"))
out["echo_031b_audit_documents_in_home"] = echo
out["notes"].append("Echo's 0.31b audit document: " + (", ".join(echo) if echo else "NOT PRESENT in the Abraham home"))

# 10. configuration
efi = W / "third_party" / "limine-12.9.6" / "extracted" / "limine-binary" / "BOOTX64.EFI"
check("config.limine_efi", sha(efi) == LIMINE, sha(efi))
out["config_limine_conf_sha256"] = sha(W / "boot" / "limine.conf")

# 11. QEMU
qexe = QEMU_DIR / "qemu-system-x86_64.exe"
try:
    r = subprocess.run([str(qexe), "--version"], capture_output=True, text=True, timeout=60)
    ver = (r.stdout + r.stderr).strip().splitlines()[0]
except Exception as e:  # noqa: BLE001
    ver = f"UNAVAILABLE: {e}"
check("qemu.1110", qexe.is_file() and sha(qexe) == QEMU_SHA and "11.1.0" in ver, {"sha256": sha(qexe), "version": ver})

# checkpoint of the whole accepted 0.31b tree
cp = Path(sys.argv[2])
lines = [f"{sha(p)}  {p.relative_to(HOME)}" for p in sorted(W.rglob("*")) if p.is_file()]
cp.write_text("\n".join(lines) + "\n")
out["checkpoint"] = {"path": str(cp), "files": len(lines), "sha256": sha(cp)}

out["verdict"] = "0.31b STARTING STATE VERIFIED" if not out["fail"] else "0.31b STARTING STATE DISCREPANCY"
Path(sys.argv[1]).write_text(json.dumps(out, indent=1) + "\n")
print(out["verdict"], "fail:", out["fail"])
for k, v in out["checks"].items():
    print(("OK  " if v["ok"] else "FAIL"), k)
print("index mismatches:", json.dumps(out["checks"]["index.entries"]["detail"]["mismatches"], indent=1))
print("append-only:", out["checks"]["index.entries"]["detail"]["append_only"])
print("source drift:", json.dumps(out["checks"]["source.unchanged_since_campaign"]["detail"], indent=1))
print("records:", out["checks"]["records.tr0033_tr0035"]["detail"]["last_record_in_index"],
      "next", out["checks"]["records.tr0033_tr0035"]["detail"]["next_free"])
print("decisions:", out["checks"]["decisions.d001_d017"]["detail"]["last"],
      "next", out["checks"]["decisions.d001_d017"]["detail"]["next_free"])
print("zip members differing from disk now:", zdiff)
print("notes:", out["notes"])
print("checkpoint:", out["checkpoint"])
sys.exit(0 if not out["fail"] else 1)
