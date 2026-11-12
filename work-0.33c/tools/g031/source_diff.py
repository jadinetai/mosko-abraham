"""ABRAHAM 0.31a: unified source diff work-0.29 -> work-0.31 (kernel/, boot/, tools/, docs/).

  python -I tools/g031/source_diff.py <out.patch>

Covers added, removed and changed text files; skips build output, target/ and __pycache__/.
Prints a per-file summary (added/removed lines). Standard library only.
"""
import difflib
import sys
from pathlib import Path

W31 = Path(__file__).resolve().parents[2]
# 0.31b: `--from <tree name>` diffs against another tree (e.g. work-0.31); default work-0.29.
W29 = W31.parent / (sys.argv[sys.argv.index("--from") + 1] if "--from" in sys.argv else "work-0.29")
DIRS = ("kernel", "boot", "tools", "docs")
SKIP = {"target", "__pycache__"}


def files(root):
    out = set()
    for d in DIRS:
        for p in (root / d).rglob("*"):
            if p.is_file() and not (SKIP & set(p.relative_to(root).parts)):
                out.add(p.relative_to(root).as_posix())
    return out


def read(p):
    return p.read_text(encoding="utf-8").replace("\r\n", "\n").splitlines(keepends=True) if p.is_file() else []


def main():
    out = Path(sys.argv[1])
    chunks, summary = [], []
    for rel in sorted(files(W29) | files(W31)):
        a, b = read(W29 / rel), read(W31 / rel)
        if a == b:
            continue
        d = list(difflib.unified_diff(a, b, fromfile=f"{W29.name}/{rel}" if a else "/dev/null",
                                      tofile=f"{W31.name}/{rel}" if b else "/dev/null", n=3))
        chunks.extend(d if d[-1].endswith("\n") else d + ["\n"])
        plus = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
        minus = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
        status = "added" if not a else "removed" if not b else "changed"
        summary.append(f"{status:8s} +{plus:<5d} -{minus:<5d} {rel}")
    out.write_text("".join(chunks), encoding="utf-8", newline="\n")
    print("\n".join(summary))
    print(f"{len(summary)} files differ; patch {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
