"""ABRAHAM 0.31a: create the isolated 0.31 development tree from the accepted 0.29 sources.

  python -I tools/g031/branch_from_029.py

Copies only source inputs (kernel/, boot/, tools/, docs/, README.md) and the Limine
BOOTX64.EFI from work-0.29 into work-0.31. Nothing in work-0.29 or frozen/ is written.
Every copied file is re-hashed after the copy and compared with:
  - the source file in work-0.29 (byte-identical copy), and
  - the 0.29 sign-off index EVIDENCE_INDEX_0.29_SIGNOFF.sha256 where that file is listed.
Writes COPY_MANIFEST_FROM_0.29.json. Refuses to overwrite an existing copy.
Standard library only.
"""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
SRC = HOME / "work-0.29"
DST = HOME / "work-0.31"
SIGNOFF = SRC / "EVIDENCE_INDEX_0.29_SIGNOFF.sha256"
SIGNOFF_SHA = "98d15717b35790435ef46fbb34aec5abbbbf25d0f7e151af0dde1b1184e3449f"
DIRS = ("kernel", "boot", "tools", "docs")
FILES = ("README.md", "third_party/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI",
         "third_party/limine-12.9.6/extracted/limine-binary/LICENSE")
SKIP_PARTS = {"target", "__pycache__"}
SELF = Path(__file__).resolve()


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    if sha(SIGNOFF) != SIGNOFF_SHA:
        raise SystemExit(f"REFUSED: sign-off index digest {sha(SIGNOFF)} is not the accepted {SIGNOFF_SHA}")
    if (DST / "COPY_MANIFEST_FROM_0.29.json").exists() or (DST / "kernel").exists():
        raise SystemExit("REFUSED: work-0.31 already holds a copy; never overwrite it")
    index = {}
    for line in SIGNOFF.read_text().splitlines():
        digest, kind, rel = line.split("  ")
        if rel.startswith("work-0.29\\"):
            index[rel[len("work-0.29\\"):].replace("\\", "/")] = (digest, kind)

    rels = []
    for d in DIRS:
        for p in sorted((SRC / d).rglob("*")):
            if p.is_file() and not (SKIP_PARTS & set(p.relative_to(SRC).parts)):
                rels.append(p.relative_to(SRC).as_posix())
    rels += list(FILES)

    copied, bad = {}, []
    for rel in rels:
        s, t = SRC / rel, DST / rel
        if t.resolve() == SELF:  # this script was written first; it is new, not copied
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        before = sha(s)
        shutil.copyfile(s, t)
        after_src, after_dst = sha(s), sha(t)
        entry = {"sha256": after_dst, "source_unchanged": before == after_src, "identical": after_src == after_dst}
        if rel in index:
            entry["signoff_kind"], entry["matches_signoff"] = index[rel][1], index[rel][0] == after_dst
        copied[rel] = entry
        if not entry["identical"] or not entry["source_unchanged"] or entry.get("matches_signoff") is False:
            bad.append(rel)

    listed_sources = {r for r, (_, k) in index.items() if k in ("kernel-source", "tool")}
    missing_from_copy = sorted(listed_sources - set(copied))
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_tree": str(SRC), "destination_tree": str(DST),
        "signoff_index_sha256": SIGNOFF_SHA,
        "files_copied": len(copied),
        "files_matching_signoff": sum(1 for e in copied.values() if e.get("matches_signoff")),
        "signoff_sources_not_copied": missing_from_copy,
        "mismatches": bad,
        "not_copied_by_design": ["work-0.29/evidence (sealed 0.29 runs stay where they are)",
                                 "work-0.29/build (0.29 binaries, including the frozen 0.1.0 copy)",
                                 "work-0.29 evidence indexes and review"],
        "new_file_not_from_0.29": SELF.relative_to(DST).as_posix(),
        "files": copied,
    }
    (DST / "COPY_MANIFEST_FROM_0.29.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    ok = not bad and not missing_from_copy
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, indent=1))
    print("BRANCH COPY VERIFIED" if ok else "BRANCH COPY DISCREPANCY")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
