"""ABRAHAM 0.32: prove a preserved tree is unchanged since its checkpoint (read-only; writes only its report).

  python -I -B tools/g032/verify_tree_checkpoint.py <tree name, e.g. work-0.31b> <checkpoint.sha256> <out.json>

Re-hashes every file listed in the checkpoint and lists any file that changed, disappeared or appeared in the tree
since then. The generalized form of work-0.31b/tools/g031b/verify_checkpoint.py (which is fixed to work-0.31).
Standard library only.
"""
import hashlib
import json
import sys
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
PRESERVED = {"work-0.29", "work-0.31", "work-0.31b", "work-0.32", "work-0.32b"}  # 0.32b adds work-0.32; 0.33 adds work-0.32b


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    tree, cp, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    if tree not in PRESERVED:
        raise SystemExit(f"REFUSED: {tree} is not a preserved tree")
    listed = dict((l.split("  ", 1)[1], l.split("  ", 1)[0]) for l in cp.read_text().splitlines() if l.strip())
    foreign = sorted(r for r in listed if not r.startswith(tree + "\\"))
    if foreign:
        raise SystemExit(f"REFUSED: checkpoint lists files outside {tree}: {foreign[:3]}")
    now = {str(p.relative_to(HOME)) for p in (HOME / tree).rglob("*") if p.is_file()}
    changed = sorted(r for r, d in listed.items() if (HOME / r).is_file() and sha(HOME / r) != d)
    missing = sorted(r for r in listed if not (HOME / r).is_file())
    added = sorted(now - set(listed))
    ok = not (changed or missing or added)
    report = {"tree": tree, "checkpoint": str(cp), "checkpoint_sha256": sha(cp), "files": len(listed),
              "changed": changed, "missing": missing, "added": added,
              "verdict": f"{tree} UNCHANGED" if ok else f"{tree} CHANGED"}
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
