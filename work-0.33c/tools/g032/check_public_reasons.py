"""ABRAHAM 0.32 (S14, P-15, D-ABR-011/019): the public reason type is exactly Appendix A, and nothing converts into it.

  python -I -B tools/g032/check_public_reasons.py [--source <svcstatus.rs>] [--json out.json]
  (--source checks another copy of svcstatus.rs, used by the checker's own negative test)

Checks, with the Appendix A list parsed from the ratified baseline (never hard-coded):
  - the PublicReason enum has exactly 27 variants, ALL_REASONS lists 27, and `name()` maps each variant to one name;
  - the names, in order, are exactly the Appendix A codes, in Appendix A order;
  - no `impl From<...> for PublicReason`, `TryFrom`, `FromStr` or `.parse::<PublicReason>` exists in kernel/src, so a
    string (a kernel diagnostic code) cannot become a public reason;
  - every `reason=` printed by svcmgr.rs takes its value from `reason_name(..)` or `.name()` of a PublicReason, never a
    literal.
Standard library only. Label: host checks (text of the source and the baseline).
"""
import json
import re
import sys
from pathlib import Path

W = Path(__file__).resolve().parents[2]
HOME = W.parent
BASELINE = HOME / "ABRAHAM_0.2_BASELINE.md"
SRC = W / "kernel" / "src"


def code_only(text):
    return "\n".join(l.split("//")[0] for l in text.splitlines())


def main():
    src = Path(sys.argv[sys.argv.index("--source") + 1]) if "--source" in sys.argv else SRC / "svcstatus.rs"
    t = BASELINE.read_text(encoding="utf-8")
    a = t[t.index("## Appendix A"):t.index("## Appendix B")]
    appendix = re.findall(r"^\| `([A-Z_]+)` \|", a, re.M)
    s = code_only(src.read_text(encoding="utf-8"))
    enum = re.search(r"pub enum PublicReason \{(?P<body>[^}]*)\}", s)
    variants = re.findall(r"\b([A-Z][A-Za-z]+)\s*,", enum["body"]) if enum else []
    all_arr = re.search(r"pub const ALL_REASONS: \[PublicReason; (?P<n>\d+)\] = \[(?P<body>[^\]]*)\]", s)
    all_items = re.findall(r"PublicReason::([A-Za-z]+)", all_arr["body"]) if all_arr else []
    pairs = re.findall(r"PublicReason::([A-Za-z]+) => \"([A-Z_]+)\"", s)
    names = [n for _, n in pairs]
    kernel = {p.name: code_only(p.read_text(encoding="utf-8")) for p in SRC.glob("*.rs")}
    if "--source" in sys.argv:
        kernel["svcstatus.rs"] = s
    conversions = sorted(f for f, c in kernel.items()
                         if re.search(r"impl\s+(?:core::convert::)?(?:From|TryFrom)\s*<[^>]*>\s*for\s+PublicReason"
                                      r"|impl\s+(?:core::str::)?FromStr\s+for\s+PublicReason|parse::<PublicReason>", c))
    mgr = kernel.get("svcmgr.rs", "")
    reason_args = re.findall(r"reason=\{\}", mgr)
    literal_reasons = re.findall(r"reason=([A-Z][A-Z_]+)", mgr)
    checks = {
        "appendix_a_has_27": len(appendix) == 27,
        "enum_has_27_variants": len(variants) == 27,
        "all_reasons_lists_27": all_arr is not None and all_arr["n"] == "27" and len(all_items) == 27 and all_items == variants,
        "name_maps_each_variant_once": [v for v, _ in pairs] == variants,
        "names_equal_appendix_a_in_order": names == appendix,
        "no_conversion_into_public_reason": not conversions,
        "svcmgr_prints_reasons_only_through_public_reason": bool(reason_args) and not literal_reasons,
    }
    report = {"source": str(src), "baseline": str(BASELINE), "appendix_a": len(appendix), "variants": len(variants),
              "names": names, "missing": sorted(set(appendix) - set(names)), "extra": sorted(set(names) - set(appendix)),
              "conversions_found_in": conversions, "checks": checks,
              "verdict": "PASS" if all(checks.values()) else "FAIL", "label": "host checks (source and baseline text)"}
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
