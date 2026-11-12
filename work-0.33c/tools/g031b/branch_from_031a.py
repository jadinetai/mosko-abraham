"""ABRAHAM 0.31b: create the 0.31b working copy from the reviewed 0.31a sources.

  python -I -B tools/g031b/branch_from_031a.py

Copies kernel/, boot/, tools/, docs/, README.md and the Limine BOOTX64.EFI/LICENSE from work-0.31 into
work-0.31b (no evidence, no build output). Nothing in work-0.31 is written. Each copied file is re-hashed
and compared with its work-0.31 source and, where listed, with EVIDENCE_INDEX_0.31a.sha256. Files that
already exist in work-0.31b (the 0.31b tools written first) are never overwritten. Writes
COPY_MANIFEST_FROM_0.31a.json. Standard library only.
"""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
SRC, DST = HOME / "work-0.31", HOME / "work-0.31b"
INDEX = SRC / "EVIDENCE_INDEX_0.31a.sha256"
INDEX_SHA = "16f02153670879c68fb20a0f720df2296f7f9cf067a1e5c94b29d4ce120642e6"
DIRS = ("kernel", "boot", "tools", "docs")
FILES = ("README.md", "third_party/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI",
         "third_party/limine-12.9.6/extracted/limine-binary/LICENSE")
SKIP = {"target", "__pycache__"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    if sha(INDEX) != INDEX_SHA:
        raise SystemExit("REFUSED: 0.31a evidence index digest changed")
    if (DST / "COPY_MANIFEST_FROM_0.31a.json").exists() or (DST / "kernel").exists():
        raise SystemExit("REFUSED: work-0.31b already holds a copy")
    index = {}
    for line in INDEX.read_text().splitlines():
        d, kind, rel = line.split("  ")
        if rel.startswith("work-0.31\\"):
            index[rel[len("work-0.31\\"):].replace("\\", "/")] = (d, kind)
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
        e = {"sha256": sha(t), "identical": sha(t) == sha(s) == before}
        if rel in index:
            e["indexed_kind"] = index[rel][1]
            e["matches_index"] = index[rel][0] == e["sha256"]
        copied[rel] = e
        if not e["identical"] or (e.get("matches_index") is False and index[rel][1] != "document"):
            bad.append(rel)
    doc_differs = sorted(r for r, e in copied.items() if e.get("matches_index") is False)
    m = {"created_utc": datetime.now(timezone.utc).isoformat(), "source_tree": str(SRC), "destination_tree": str(DST),
         "index_sha256": INDEX_SHA, "files_copied": len(copied),
         "files_matching_index": sum(1 for e in copied.values() if e.get("matches_index")),
         "documents_differing_from_index": doc_differs, "not_overwritten_existing_0_31b_files": kept,
         "mismatches": bad, "files": copied}
    (DST / "COPY_MANIFEST_FROM_0.31a.json").write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in m.items() if k != "files"}, indent=1))
    print("BRANCH COPY VERIFIED" if not bad else "BRANCH COPY DISCREPANCY")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
