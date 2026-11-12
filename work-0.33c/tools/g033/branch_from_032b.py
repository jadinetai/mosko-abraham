"""ABRAHAM 0.33 Step 1: verify the accepted 0.32b state, checkpoint work-0.32b, and create the 0.33 copy (D-ABR-022/023).

  python -I -B tools/g033/branch_from_032b.py

Run ABR-0.33-V001 (read-only on work-0.32b; writes only into work-0.33):
  1. the accepted digests (D-ABR-023): kernel 81d4b4ec, evidence index c69a91e0, TR-0038 package 7abf391a;
  2. every row of EVIDENCE_INDEX_0.32b.sha256 (DECISIONS.md and test-records/INDEX.md as whole-line prefixes: they
     are append-only), and every member of every RUN_SHA256SUMS.json under work-0.32b/evidence;
  3. a full-tree checkpoint of work-0.32b (every file), so the end of 0.33 can prove work-0.32b was never written.
Run ABR-0.33-V002: copies kernel/, boot/, tools/, docs/, README.md and the Limine BOOTX64.EFI/LICENSE (no evidence,
no build output) into work-0.33. Each copied file is hashed before and after, and compared with the checkpoint and,
where listed, with the index. Files that already exist in work-0.33 (this tool) are never overwritten.
Writes evidence/start/ABR-0.33-V001/, evidence/start/ABR-0.33-V002/ (sealed) and COPY_MANIFEST_FROM_0.32b.json.
Refuses to run twice. Standard library only.
"""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
SRC = HOME / "work-0.32b"
DST = Path(__file__).resolve().parents[2]
INDEX = SRC / "EVIDENCE_INDEX_0.32b.sha256"
INDEX_SHA = "c69a91e0ce413afcbecd216dc910bbaeb1c5a0cd21313c2bf6cf07cc3682a81a"
KERNEL_SHA = "81d4b4ec86684f45a4e6ebb81cdf3e1532679d8c3711049a54b17ed486f64679"
ZIP_SHA = "7abf391af5ce00515f4ff949dc106bb183d4b0fd311de0011b1de7034526fee3"
APPEND_ONLY = {"DECISIONS.md", "test-records\\INDEX.md"}
DIRS = ("kernel", "boot", "tools", "docs")
FILES = ("README.md", "third_party/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI",
         "third_party/limine-12.9.6/extracted/limine-binary/LICENSE")
SKIP = {"target", "__pycache__"}


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def sha(p):
    return sha_b(Path(p).read_bytes())


def utc():
    return datetime.now(timezone.utc).isoformat()


def seal(d):
    sums = {p.relative_to(d).as_posix(): sha(p) for p in sorted(d.rglob("*")) if p.is_file() and p.name != "RUN_SHA256SUMS.json"}
    (d / "RUN_SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n")


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


def v001(run):
    fail, rep = [], {"run_id": "ABR-0.33-V001", "label": "host", "started_utc": utc()}
    rep["index_sha256"] = sha(INDEX)
    rep["kernel_sha256"] = sha(SRC / "build" / "abraham-kernel-0.32.1-dev.elf")
    rep["tr0038_package_sha256"] = sha(SRC / "evidence" / "review" / "ABRAHAM_0.32b_ECHO_AUDIT.zip")
    for k, want in (("index_sha256", INDEX_SHA), ("kernel_sha256", KERNEL_SHA), ("tr0038_package_sha256", ZIP_SHA)):
        if rep[k] != want:
            fail.append(k)
    rows, append, mism = 0, {}, []
    for line in INDEX.read_text().splitlines():
        d, kind, rel = line.split("  ", 2)
        rows += 1
        p = HOME / rel
        if not p.is_file():
            mism.append(f"{rel} missing")
        elif rel in APPEND_ONLY:
            append[rel] = prefix_ok(p, d)
            if not append[rel]:
                mism.append(f"{rel} not an append-only extension")
        elif sha(p) != d:
            mism.append(f"{rel} ({kind}) differs")
    rep.update(index_rows=rows, append_only=append, index_mismatches=mism)
    fail += mism
    seals = members = 0
    for s in sorted((SRC / "evidence").rglob("RUN_SHA256SUMS.json")):
        seals += 1
        for name, d in json.loads(s.read_text()).items():
            members += 1
            f = s.parent / name
            if not f.is_file() or sha(f) != d:
                fail.append(f"seal {f.relative_to(HOME)}")
    rep.update(run_seals=seals, sealed_members=members)
    lines = [f"{sha(p)}  {p.relative_to(HOME)}" for p in sorted(SRC.rglob("*")) if p.is_file()]
    (run / "CHECKPOINT_work-0.32b.sha256").write_text("\n".join(lines) + "\n")
    rep.update(checkpoint_files=len(lines), checkpoint_sha256=sha(run / "CHECKPOINT_work-0.32b.sha256"),
               failures=fail, verdict="0.32b ACCEPTED STATE VERIFIED" if not fail else "DISCREPANCY", ended_utc=utc())
    (run / "result.json").write_text(json.dumps(rep, indent=1) + "\n")
    seal(run)
    return rep, {l.split("  ", 1)[1][len("work-0.32b\\"):].replace("\\", "/"): l.split("  ", 1)[0] for l in lines}


def v002(run, checkpoint):
    index = {}
    for line in INDEX.read_text().splitlines():
        d, kind, rel = line.split("  ", 2)
        if rel.startswith("work-0.32b\\"):
            index[rel[len("work-0.32b\\"):].replace("\\", "/")] = (d, kind)
    rels = [p.relative_to(SRC).as_posix() for d in DIRS for p in sorted((SRC / d).rglob("*"))
            if p.is_file() and not (SKIP & set(p.relative_to(SRC).parts))] + list(FILES)
    copied, bad, kept = {}, [], []
    for rel in rels:
        s, t = SRC / rel, DST / rel
        if t.exists():
            kept.append(rel)
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        before = sha(s)
        shutil.copyfile(s, t)
        e = {"sha256": sha(t)}
        e["identical"] = e["sha256"] == before == sha(s)
        e["matches_checkpoint"] = checkpoint.get(rel) == e["sha256"]
        if rel in index:
            e["indexed_kind"], e["matches_index"] = index[rel][1], index[rel][0] == e["sha256"]
        copied[rel] = e
        if not e["identical"] or not e["matches_checkpoint"] or e.get("matches_index") is False:
            bad.append(rel)
    m = {"run_id": "ABR-0.33-V002", "created_utc": utc(), "source_tree": str(SRC), "destination_tree": str(DST),
         "index_sha256": INDEX_SHA, "files_copied": len(copied),
         "files_matching_checkpoint": sum(1 for e in copied.values() if e["matches_checkpoint"]),
         "files_listed_in_index": sum(1 for e in copied.values() if "matches_index" in e),
         "files_matching_index": sum(1 for e in copied.values() if e.get("matches_index")),
         "files_not_in_index": sorted(r for r, e in copied.items() if "matches_index" not in e),
         "not_overwritten_existing_0_33_files": kept, "mismatches": bad,
         "verdict": "BRANCH COPY VERIFIED" if not bad else "BRANCH COPY DISCREPANCY", "files": copied}
    (DST / "COPY_MANIFEST_FROM_0.32b.json").write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
    (run / "copy_summary.json").write_text(json.dumps({k: v for k, v in m.items() if k != "files"}, indent=1) + "\n")
    shutil.copyfile(DST / "COPY_MANIFEST_FROM_0.32b.json", run / "COPY_MANIFEST_FROM_0.32b.json")
    seal(run)
    return m


def main():
    start = DST / "evidence" / "start"
    if (DST / "COPY_MANIFEST_FROM_0.32b.json").exists() or (DST / "kernel").exists() or start.exists():
        raise SystemExit("REFUSED: work-0.33 already holds a copy")
    r1, r2 = start / "ABR-0.33-V001", start / "ABR-0.33-V002"
    r1.mkdir(parents=True)
    rep, checkpoint = v001(r1)
    print(json.dumps({k: v for k, v in rep.items() if k not in ("append_only",)}, indent=1))
    if rep["failures"]:
        return 1
    r2.mkdir()
    m = v002(r2, checkpoint)
    print(json.dumps({k: v for k, v in m.items() if k != "files"}, indent=1))
    return 0 if not m["mismatches"] else 1


if __name__ == "__main__":
    sys.exit(main())
