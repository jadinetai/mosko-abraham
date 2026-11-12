"""ABRAHAM 0.31b: prove the reviewed 0.31a tree is unchanged since the Step 1 checkpoint.

  python -I -B tools/g031b/verify_checkpoint.py <CHECKPOINT_work-0.31.sha256> <out.json>

Re-hashes every file listed in the checkpoint (taken in Step 1, run V002) and lists any file that
changed, disappeared or appeared in work-0.31 since then. Read-only. Standard library only.
"""
import hashlib
import json
import sys
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    cp, out = Path(sys.argv[1]), Path(sys.argv[2])
    listed = dict((l.split("  ", 1)[1], l.split("  ", 1)[0]) for l in cp.read_text().splitlines() if l.strip())
    now = {str(p.relative_to(HOME)) for p in (HOME / "work-0.31").rglob("*") if p.is_file()}
    changed = sorted(r for r, d in listed.items() if (HOME / r).is_file() and sha(HOME / r) != d)
    missing = sorted(r for r in listed if not (HOME / r).is_file())
    added = sorted(now - set(listed))
    report = {"checkpoint": str(cp), "checkpoint_sha256": sha(cp), "files": len(listed),
              "changed": changed, "missing": missing, "added": added,
              "verdict": "0.31a TREE UNCHANGED" if not (changed or missing or added) else "0.31a TREE CHANGED"}
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return 0 if not (changed or missing or added) else 1


if __name__ == "__main__":
    sys.exit(main())
