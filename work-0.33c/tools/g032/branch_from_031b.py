"""ABRAHAM 0.32: create the 0.32 working copy from the accepted 0.31b sources (D-ABR-017).

  python -I -B tools/g032/branch_from_031b.py <CHECKPOINT_work-0.31b.sha256>

Copies kernel/, boot/, tools/, docs/, README.md and the Limine BOOTX64.EFI/LICENSE from work-0.31b into work-0.32
(no evidence, no build output). Nothing in work-0.31b is written. Each copied file is re-hashed and compared with
  - its work-0.31b source before and after the copy,
  - the Step 1 full-tree checkpoint of work-0.31b (run ABR-0.32-V001), which every copied file must be listed in,
  - and, where listed, EVIDENCE_INDEX_0.31b.sha256 (only 'document' entries may differ; each is reported).
Files that already exist in work-0.32 (the 0.32 tools written first) are never overwritten.
Writes COPY_MANIFEST_FROM_0.31b.json. Standard library only.
"""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
SRC, DST = HOME / "work-0.31b", HOME / "work-0.32"
INDEX = SRC / "EVIDENCE_INDEX_0.31b.sha256"
INDEX_SHA = "81b565fb3b5d9a3bdc375236fec4ada65cd0db0631ae4c06ae047fbd8edafa71"
DIRS = ("kernel", "boot", "tools", "docs")
FILES = ("README.md", "third_party/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI",
         "third_party/limine-12.9.6/extracted/limine-binary/LICENSE")
SKIP = {"target", "__pycache__"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    cp_path = Path(sys.argv[1])
    if sha(INDEX) != INDEX_SHA:
        raise SystemExit("REFUSED: 0.31b evidence index digest changed")
    if (DST / "COPY_MANIFEST_FROM_0.31b.json").exists() or (DST / "kernel").exists():
        raise SystemExit("REFUSED: work-0.32 already holds a copy")
    checkpoint = {}
    for line in cp_path.read_text().splitlines():
        if line.strip():
            d, rel = line.split("  ", 1)
            if rel.startswith("work-0.31b\\"):
                checkpoint[rel[len("work-0.31b\\"):].replace("\\", "/")] = d
    index = {}
    for line in INDEX.read_text().splitlines():
        d, kind, rel = line.split("  ")
        if rel.startswith("work-0.31b\\"):
            index[rel[len("work-0.31b\\"):].replace("\\", "/")] = (d, kind)
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
        after_src, dst = sha(s), sha(t)
        e = {"sha256": dst, "identical": dst == before == after_src,
             "matches_checkpoint": checkpoint.get(rel) == dst}
        if rel in index:
            e["indexed_kind"] = index[rel][1]
            e["matches_index"] = index[rel][0] == dst
        copied[rel] = e
        if not e["identical"] or not e["matches_checkpoint"] \
                or (e.get("matches_index") is False and index[rel][1] != "document"):
            bad.append(rel)
    doc_differs = sorted(r for r, e in copied.items() if e.get("matches_index") is False)
    m = {"created_utc": datetime.now(timezone.utc).isoformat(), "source_tree": str(SRC), "destination_tree": str(DST),
         "index_sha256": INDEX_SHA, "checkpoint": str(cp_path), "checkpoint_sha256": sha(cp_path),
         "files_copied": len(copied),
         "files_matching_checkpoint": sum(1 for e in copied.values() if e["matches_checkpoint"]),
         "files_listed_in_index": sum(1 for e in copied.values() if "matches_index" in e),
         "files_matching_index": sum(1 for e in copied.values() if e.get("matches_index")),
         "files_not_in_index": sorted(r for r, e in copied.items() if "matches_index" not in e),
         "documents_differing_from_index": doc_differs, "not_overwritten_existing_0_32_files": kept,
         "mismatches": bad, "files": copied}
    (DST / "COPY_MANIFEST_FROM_0.31b.json").write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in m.items() if k != "files"}, indent=1))
    print("BRANCH COPY VERIFIED" if not bad else "BRANCH COPY DISCREPANCY")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
