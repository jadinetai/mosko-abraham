"""ABRAHAM 0.31a: every kernel diagnostic code must be registered (D-ABR-012).

  python -I tools/g031/check_diag_codes.py [--json out.json] [--root <tree>]
  (--root checks another copy of the tree, used by the checker's own negative test)

Collects, from kernel/src/*.rs and kernel/asm/entry.asm:
  - every standalone ALL-CAPS string literal ("OUT_OF_MEMORY", "PAGE_FAULT", ...);
  - every ALL-CAPS value after reason= / violation= / detail= / code= / owner= / state= inside
    format strings;
  - every line tag ABR|<TAG>|.
Every one must appear as a backticked code in the first column of a table in
docs/KERNEL_DIAGNOSTICS.md. Unregistered codes FAIL. Registered codes that the source no longer
contains are listed as INFO (they may be historical). Standard library only.
"""
import json
import re
import sys
from pathlib import Path

OS = Path(sys.argv[sys.argv.index("--root") + 1]).resolve() if "--root" in sys.argv else Path(__file__).resolve().parents[2]
REGISTRY = OS / "docs" / "KERNEL_DIAGNOSTICS.md"
SOURCES = sorted((OS / "kernel" / "src").glob("*.rs")) + [OS / "kernel" / "asm" / "entry.asm"]
# Not diagnostic codes: build-time environment variable names.
NOT_CODES = {"CARGO_PKG_VERSION"}

LITERAL = re.compile(r'"([A-Z][A-Z0-9_]{2,})"')
KEYED = re.compile(r"(?:reason|violation|detail|code|owner|state)=([A-Z][A-Z0-9_]{2,})")
# 0.31b: also a tag written as a string on its own ("ABR|EVENT"), which has no trailing '|'.
TAG = re.compile(r"ABR\|([A-Z_]+)(?:\||\")")
ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|")


def main():
    registered = set()
    for line in REGISTRY.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            registered.add(m.group(1))
    found = {}
    for src in SOURCES:
        text = src.read_text(encoding="utf-8")
        for rx in (LITERAL, KEYED, TAG):
            for m in rx.finditer(text):
                found.setdefault(m.group(1), set()).add(src.name)
    found = {k: v for k, v in found.items() if k not in NOT_CODES}
    unregistered = sorted(set(found) - registered)
    unused = sorted(registered - set(found))
    report = {"registry": str(REGISTRY.relative_to(OS)), "registered": len(registered), "found_in_source": len(found),
              "unregistered": {k: sorted(found[k]) for k in unregistered}, "registered_not_in_source": unused,
              "result": "PASS" if not unregistered else "FAIL"}
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return 0 if not unregistered else 1


if __name__ == "__main__":
    raise SystemExit(main())
