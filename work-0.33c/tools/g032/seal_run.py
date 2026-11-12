"""ABRAHAM 0.32: seal a finished host-check run folder (same format as the harness seal in abr_boot_001.py).

  python -I -B tools/g032/seal_run.py <run_dir> [<run_dir> ...]

Writes RUN_SHA256SUMS.json (every file in the folder except the seal itself, sorted) and re-hashes every member.
Refuses a folder that already has a seal: a seal is written once. Standard library only.
"""
import hashlib
import json
import sys
from pathlib import Path


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    bad = 0
    for arg in sys.argv[1:]:
        d = Path(arg)
        if (d / "RUN_SHA256SUMS.json").exists():
            print(f"REFUSED: {d} is already sealed")
            bad += 1
            continue
        sums = {p.relative_to(d).as_posix(): sha(p) for p in sorted(d.rglob("*")) if p.is_file()}
        (d / "RUN_SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n")
        ok = all(sha(d / n) == v for n, v in sums.items())
        print(f"{'SEALED' if ok else 'SEAL RECHECK FAILED'} {d} members={len(sums)} seal={sha(d / 'RUN_SHA256SUMS.json')}")
        bad += 0 if ok else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
