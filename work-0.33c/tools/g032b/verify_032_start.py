"""ABRAHAM 0.32b Step 1: verify the exact 0.32 starting state (read-only; writes only its outputs).

  python -I -B tools/g032b/verify_032_start.py <report.json> <checkpoint_work-0.32.sha256>

Checks, against what 0.32 recorded (TR-0036, TR-0037):
  1. EVIDENCE_INDEX_0.32.sha256 digest (3d380a3c...), then every entry (DECISIONS.md and INDEX.md as whole-line
     prefixes; only 'document' entries may differ, and each one is listed);
  2. every RUN_SHA256SUMS.json under work-0.32/evidence, every member (70 seals, 1,072 members recorded);
  3. BUILD_MANIFEST.json kernels (20); the 0.32 kernel = 04878ad5... with the 0.32.0-dev version string;
  4. kernel/, tools/, boot/ now vs campaign-032 SOURCE_MANIFEST_END.json: exactly the post-close changes the
     supplement recorded (judge_selftest_032.py changed; 4 tools added);
  5. the audit zip and its .sha256 (5e11bdcd...); the source diff digest;
  6. campaign.json (68 runs, 67 as expected, only ABR-0.32-J001 unexpected, no source change during the campaign)
     and supplement.json (ABR-0.32-J005 as expected);
  7. records: TR-0036, TR-0037 and their INDEX rows; INDEX's last record is TR-0037 (next free TR-0038);
  8. decisions: D-ABR-001..019 once each, in order; D-ABR-019 is the last row (no D-ABR-020 yet), and NO row
     records an acceptance of 0.32 (reported either way);
  9. the 0.32 directive and handoff digests as recorded in TR-0036; the two root copies of the 0.32 review and
     patch notes (2026-11-08) compared with the indexed documents;
 10. the pinned QEMU 11.1.0 executable digest and its reported version.
Writes a full-tree checkpoint of work-0.32 (every file), so 0.32b can prove at the end that the 0.32 tree was not
changed. Never writes into work-0.32. Standard library only.
"""
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
W = HOME / "work-0.32"
INDEX = W / "EVIDENCE_INDEX_0.32.sha256"
INDEX_SHA = "3d380a3ca423f0211ee49d3753b80076b9ada9826f5cf68b81be7258e8bb07a2"
ZIP = W / "evidence" / "review" / "ABRAHAM_0.32_ECHO_AUDIT.zip"
ZIP_SHA = "5e11bdcd154ca794ca293e486836dbc978d7b39ecec8da12cbf428b1b113c200"
DIFF_SHA = "3b28effccd9a0bd1fbcb0ad6bb360c034d7a6ec569abc38bf002a4567075e05f"
KERNEL = W / "build" / "abraham-kernel-0.32.0-dev.elf"
KERNEL_SHA = "04878ad50645db2c19db42ac9ff7c99298c143a4cbc48badcb15b9c54669c040"
DIRECTIVE_SHA = "5d39d14814f016a4f55fbcd919cccc389a0741792d29370745a8a38f15c2d9ba"
HANDOFF_SHA = "dd2a64b954ef223033614e1301c7bc3c9abd8726adf5a5b1c8d3d51579b737ca"
QEMU_DIR = Path(r"C:\Users\XxUnd\abraham-toolchain\qemu\11.1.0-weil-20260811")
QEMU_SHA = "47d57a6072e0bb3bd98f87926eb129eb1736dfe818c67b3b81ef7ce4edd0b3cd"
APPEND_ONLY = {"DECISIONS.md", "test-records\\INDEX.md"}
SKIP = {"target", "__pycache__"}
SEALS, MEMBERS, ENTRIES = 70, 1072, 394
EXPECTED_CHANGED_AFTER_CLOSE = {"tools/g032/judge_selftest_032.py"}
EXPECTED_ADDED_AFTER_CLOSE = {"tools/g032/check_checklist_032.py", "tools/g032/evidence_index_032.py",
                              "tools/g032/make_audit_032.py", "tools/g032/supplement_032.py"}


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
check("index.entries", n == ENTRIES and not [m for m in mism if m["kind"] != "document"],
      {"entries": n, "per_kind": kinds, "append_only": prefixes, "mismatches": mism})

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
bm = json.loads((W / "evidence" / "campaign-032" / "BUILD_MANIFEST.json").read_text())
kb = {}
for k, v in bm["kernels"].items():
    p = Path(v["path"]) if Path(v["path"]).is_absolute() else W / v["path"]
    kb[k] = p.is_file() and sha(p) == v["sha256"]
check("builds.manifest_kernels", len(kb) == 20 and all(kb.values()), kb)
kdata = KERNEL.read_bytes()
check("builds.kernel_032", sha_b(kdata) == KERNEL_SHA and b"0.32.0-dev" in kdata,
      {"sha256": sha_b(kdata), "version_string_0.32.0-dev": b"0.32.0-dev" in kdata})

# 4. source drift since the campaign closed
end = json.loads((W / "evidence" / "campaign-032" / "SOURCE_MANIFEST_END.json").read_text())
now = {}
for d in ("kernel", "tools", "boot"):
    for p in sorted((W / d).rglob("*")):
        if p.is_file() and not (SKIP & set(p.relative_to(W).parts)):
            now[p.relative_to(W).as_posix()] = sha(p)
changed = sorted(k for k in end if k in now and now[k] != end[k])
removed = sorted(set(end) - set(now))
added = sorted(set(now) - set(end))
check("source.post_close_changes_exactly_as_recorded",
      set(changed) == EXPECTED_CHANGED_AFTER_CLOSE and not removed and set(added) == EXPECTED_ADDED_AFTER_CLOSE,
      {"changed": changed, "removed": removed, "added_after_close": added})

# 5. audit zip and diff
zs = (ZIP.parent / (ZIP.name + ".sha256")).read_text().split()[0]
check("zip.digest", sha(ZIP) == ZIP_SHA and zs == ZIP_SHA, {"zip": sha(ZIP), "sha256_file": zs})
zdiff = []
with zipfile.ZipFile(ZIP) as z:
    for name in z.namelist():
        disk = HOME / name
        if disk.is_file() and sha_b(z.read(name)) != sha(disk):
            zdiff.append(name)
out["zip_members_differing_from_disk_now"] = zdiff
check("review.source_diff", sha(W / "evidence" / "review" / "0.32_SOURCE_DIFF_from_0.31b.patch") == DIFF_SHA, DIFF_SHA)

# 6. campaign and supplement
camp = json.loads((W / "evidence" / "campaign-032" / "campaign.json").read_text())
unexpected = [r["id"] for r in camp["runs"] if not r["as_expected"]]
sup = json.loads((W / "evidence" / "campaign-032-supplement" / "supplement.json").read_text())
check("campaign.68_with_j001_only_unexpected", len(camp["runs"]) == 68 and unexpected == ["ABR-0.32-J001"]
      and camp.get("source_changed_during_campaign") == [] and camp.get("all_as_expected") is False,
      {"runs": len(camp["runs"]), "unexpected": unexpected})
check("supplement.j005_as_expected", [(r["id"], r["as_expected"]) for r in sup["runs"]] == [("ABR-0.32-J005", True)]
      and sup["closed_campaign_sha256"] == sha(W / "evidence" / "campaign-032" / "campaign.json"),
      {"runs": [(r["id"], r["as_expected"]) for r in sup["runs"]]})

# 7. records
idx = (HOME / "test-records" / "INDEX.md").read_text(encoding="utf-8")
recs = {}
for t in ("TR-0036", "TR-0037"):
    f = HOME / "test-records" / f"{t}.md"
    recs[t] = {"file": f.is_file(), "index_row": f"| {t} |" in idx, "sha256": sha(f) if f.is_file() else None}
nums = sorted(int(m) for m in re.findall(r"^\| TR-(\d{4}) \|", idx, re.M))
check("records.tr0036_tr0037", all(r["file"] and r["index_row"] for r in recs.values()) and nums[-1] == 37,
      {"records": recs, "last_record_in_index": f"TR-{nums[-1]:04d}", "next_free": f"TR-{nums[-1] + 1:04d}",
       "index_sha256": sha(HOME / "test-records" / "INDEX.md")})

# 8. decisions
dec = (HOME / "DECISIONS.md").read_text(encoding="utf-8")
ids = re.findall(r"^\| (D-ABR-\d{3}) \|", dec, re.M)
want = [f"D-ABR-{i:03d}" for i in range(1, 20)]
acceptance_rows = [l[:80] for l in dec.splitlines() if re.search(r"0\.32 is ACCEPTED|Accept 0\.32\b|accept 0\.32\b", l)]
check("decisions.d001_d019", ids == want,
      {"rows_in_order": ids, "last": ids[-1] if ids else None, "next_free": f"D-ABR-{len(ids) + 1:03d}",
       "decisions_sha256": sha(HOME / "DECISIONS.md")})
out["decision_rows_recording_an_acceptance_of_0_32"] = acceptance_rows
out["notes"].append("0.32 acceptance on record: " + ("YES " + str(acceptance_rows) if acceptance_rows else
                    "NONE (0.32 is READY FOR AUDIT in TR-0037; no D-ABR row accepts it)"))

# 9. directives, handoff, root copies
docs = {"MOSKO_ABRAHAM_032_DEVELOPMENT_DIRECTIVE_2026-11-06.md": DIRECTIVE_SHA, "MOSKO_ABRAHAM_032_CLAUDE_HANDOFF_2026-11-05.md": HANDOFF_SHA}
check("directives.unchanged", all((HOME / n).is_file() and sha(HOME / n) == d for n, d in docs.items()),
      {n: sha(HOME / n) if (HOME / n).is_file() else None for n in docs})
copies = {}
for n in ("0.32_REVIEW.md", "PATCH_NOTES_0.32.md"):
    root, indexed = HOME / n, W / "docs" / n
    copies[n] = {"root_copy_present": root.is_file(), "identical_to_indexed": root.is_file() and sha(root) == sha(indexed)}
out["root_copies_of_0_32_documents"] = copies
echo = sorted(p.name for p in HOME.glob("*ECHO*AUDIT*.md"))
out["echo_audit_documents_in_home"] = echo
out["notes"].append("Echo audit documents in the home: " + ", ".join(echo))

# 10. QEMU
qexe = QEMU_DIR / "qemu-system-x86_64.exe"
try:
    r = subprocess.run([str(qexe), "--version"], capture_output=True, text=True, timeout=60)
    ver = (r.stdout + r.stderr).strip().splitlines()[0]
except Exception as e:  # noqa: BLE001
    ver = f"UNAVAILABLE: {e}"
check("qemu.1110", qexe.is_file() and sha(qexe) == QEMU_SHA and "11.1.0" in ver, {"sha256": sha(qexe), "version": ver})

# checkpoint of the whole 0.32 tree
cp = Path(sys.argv[2])
lines = [f"{sha(p)}  {p.relative_to(HOME)}" for p in sorted(W.rglob("*")) if p.is_file()]
cp.write_text("\n".join(lines) + "\n")
out["checkpoint"] = {"path": str(cp), "files": len(lines), "sha256": sha(cp)}

out["verdict"] = "0.32 STARTING STATE VERIFIED" if not out["fail"] else "0.32 STARTING STATE DISCREPANCY"
Path(sys.argv[1]).write_text(json.dumps(out, indent=1) + "\n")
print(out["verdict"], "fail:", out["fail"])
for k, v in out["checks"].items():
    print(("OK  " if v["ok"] else "FAIL"), k)
print("index mismatches:", json.dumps(out["checks"]["index.entries"]["detail"]["mismatches"], indent=1))
print("append-only:", out["checks"]["index.entries"]["detail"]["append_only"])
print("records:", out["checks"]["records.tr0036_tr0037"]["detail"]["last_record_in_index"],
      "next", out["checks"]["records.tr0036_tr0037"]["detail"]["next_free"])
print("decisions:", out["checks"]["decisions.d001_d019"]["detail"]["last"], "next",
      out["checks"]["decisions.d001_d019"]["detail"]["next_free"])
print("root copies:", copies)
print("zip members differing from disk now:", zdiff)
print("notes:", out["notes"])
print("checkpoint:", out["checkpoint"])
sys.exit(0 if not out["fail"] else 1)
