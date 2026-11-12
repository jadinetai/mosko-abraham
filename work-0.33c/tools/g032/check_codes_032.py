"""ABRAHAM 0.32: every printed kernel word must be registered; public reasons only in svcstatus.rs (D-ABR-011/019).

  python -I -B tools/g032/check_codes_032.py [--json out.json] [--root <tree>]
  (--root checks another copy of the tree, used by the checker's own negative test)

The 0.31a rule (tools/g031/check_diag_codes.py, unchanged there) extended for 0.32:
  - collected from kernel/src/*.rs and kernel/asm/entry.asm: every standalone ALL-CAPS string literal; every ALL-CAPS
    value after a keyed field in a format string (0.31a keys reason/violation/detail/code/owner/state, plus the 0.32
    service fields status/liveness/compromise/clock/start/registry/result/ready/diag/status_change/kind); every line
    tag ABR|<TAG>;
  - each must be a backticked first-column code in docs/KERNEL_DIAGNOSTICS.md, OR
  - be one of the 27 Appendix A reason codes of the ratified baseline (parsed from ABRAHAM_0.2_BASELINE.md) and
    occur only in kernel/src/svcstatus.rs, the single place a public reason is named (PublicReason::name).
    ENTROPY_UNAVAILABLE is the one code in both registries (registered with its Appendix A meaning since 0.29).
  - FAIL if any word is in neither, or if an Appendix A code appears as a literal outside svcstatus.rs without being
    registered (a public reason must never be written by hand on a diagnostic line).
Standard library only.
"""
import json
import re
import sys
from pathlib import Path

OS = Path(sys.argv[sys.argv.index("--root") + 1]).resolve() if "--root" in sys.argv else Path(__file__).resolve().parents[2]
HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
BASELINE = HOME / "ABRAHAM_0.2_BASELINE.md"
REGISTRY = OS / "docs" / "KERNEL_DIAGNOSTICS.md"
SOURCES = sorted((OS / "kernel" / "src").glob("*.rs")) + [OS / "kernel" / "asm" / "entry.asm"]
PUBLIC_FILE = "svcstatus.rs"
NOT_CODES = {"CARGO_PKG_VERSION"}

LITERAL = re.compile(r'"([A-Z][A-Z0-9_]{2,})"')
KEYED = re.compile(r"(?:reason|violation|detail|code|owner|state|status|liveness|compromise|clock|start|registry"
                   r"|result|ready|diag|status_change|kind)=([A-Z][A-Z0-9_]{2,})")
TAG = re.compile(r"ABR\|([A-Z_]+)(?:\||\")")
ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]+)`\s*\|")


def appendix_a():
    t = BASELINE.read_text(encoding="utf-8")
    a = t[t.index("## Appendix A"):t.index("## Appendix B")]
    return re.findall(r"^\| `([A-Z_]+)` \|", a, re.M)


def main():
    public = appendix_a()
    registered = {m.group(1) for l in REGISTRY.read_text(encoding="utf-8").splitlines() for m in [ROW.match(l)] if m}
    found = {}
    for src in SOURCES:
        text = src.read_text(encoding="utf-8")
        for rx in (LITERAL, KEYED, TAG):
            for m in rx.finditer(text):
                found.setdefault(m.group(1), set()).add(src.name)
    found = {k: v for k, v in found.items() if k not in NOT_CODES}
    public_ok = {k for k, files in found.items() if k in public and k not in registered and files == {PUBLIC_FILE}}
    public_misplaced = {k: sorted(files) for k, files in found.items()
                        if k in public and k not in registered and files != {PUBLIC_FILE}}
    unregistered = sorted(k for k in found if k not in registered and k not in public)
    in_svcstatus = sorted(k for k, f in found.items() if PUBLIC_FILE in f and k in public)
    ok = not unregistered and not public_misplaced and len(public) == 27
    report = {"registry": str(REGISTRY.relative_to(OS)), "baseline": str(BASELINE), "appendix_a_codes": len(public),
              "registered": len(registered), "found_in_source": len(found),
              "public_reason_words_in_svcstatus": len(in_svcstatus),
              "public_reason_words_missing_from_svcstatus": sorted(set(public) - set(in_svcstatus)),
              "unregistered": {k: sorted(found[k]) for k in unregistered},
              "public_reason_written_outside_svcstatus": public_misplaced,
              "in_both_registries": sorted(set(public) & registered),
              "registered_not_in_source": sorted(registered - set(found)),
              "result": "PASS" if ok else "FAIL"}
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
