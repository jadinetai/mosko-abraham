"""ABRAHAM 0.31b static checks on the production kernel and its source (host checks).

  python -I -B tools/g031b/static_checks.py <default ELF> <legacy-collision diagnostic ELF> <out.json>

One owner (directive Step 4: no private page-table allocator in production builds):
  - paging.rs gates the 0.29 bump allocator behind `#[cfg(feature = "diag-legacy-collision")]` and the
    allocator path behind its negation; Cargo.toml has no default features;
  - the default ELF does not contain the legacy path's unique string NO_FREE_FRAME, while the legacy
    diagnostic ELF does (positive control: the scan can find it).
No dynamic allocation (ABR-031-EVT-01):
  - no `extern crate alloc`, `alloc::` or `#[global_allocator]` in kernel/src;
  - the default ELF contains none of the Rust allocator symbols (__rust_alloc, __rg_alloc, __rdl_alloc,
    __rust_alloc_error_handler).
Event log without dispatch (D-ABR-015): events.rs / eventlog.rs code (comments stripped) contains no
function-pointer type, no closure parameter and none of the words handler/subscribe/dispatch/callback;
the log is a `static` with a fixed-capacity array. These are text checks of what the source says.
"""
import json
import re
import sys
from pathlib import Path

W = Path(__file__).resolve().parents[2]
SRC = W / "kernel" / "src"


def code_only(text):
    return "\n".join(l.split("//")[0] for l in text.splitlines())


def main():
    default_elf, legacy_elf, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    d, legacy = default_elf.read_bytes(), legacy_elf.read_bytes()
    paging = (SRC / "paging.rs").read_text(encoding="utf-8")
    cargo = (W / "kernel" / "Cargo.toml").read_text(encoding="utf-8")
    kernel_code = {p.name: code_only(p.read_text(encoding="utf-8")) for p in SRC.glob("*.rs")}
    ev = code_only((SRC / "events.rs").read_text(encoding="utf-8")) + code_only((SRC / "eventlog.rs").read_text(encoding="utf-8"))
    alloc_symbols = [b"__rust_alloc", b"__rg_alloc", b"__rdl_alloc", b"__rust_alloc_error_handler"]
    checks = {
        "legacy_path_gated_by_diag_feature": re.search(r'#\[cfg\(feature = "diag-legacy-collision"\)\]\s*fn take_frame', paging) is not None,
        "allocator_path_is_the_default": re.search(r'#\[cfg\(not\(feature = "diag-legacy-collision"\)\)\]\s*fn take_frame', paging) is not None,
        "no_default_features": re.search(r"^\s*default\s*=", cargo, re.M) is None,
        "default_elf_lacks_legacy_path": b"NO_FREE_FRAME" not in d,
        "control_legacy_elf_has_legacy_path": b"NO_FREE_FRAME" in legacy,
        "no_alloc_crate_in_source": not any(re.search(r"extern\s+crate\s+alloc|\balloc::|global_allocator", c)
                                            for c in kernel_code.values()),
        "default_elf_has_no_allocator_symbols": not any(s in d for s in alloc_symbols),
        "event_log_has_no_dispatch": re.search(r"\bfn\s*\(|impl\s+Fn|dyn\s+Fn|handler|subscribe|dispatch|callback", ev, re.I) is None,
        "event_log_is_static_fixed_array": "static LOG: KCell<EventLog>" in ev and "[Event; CAPACITY]" in ev,
    }
    report = {"default_elf": str(default_elf), "legacy_elf": str(legacy_elf), "checks": checks,
              "verdict": "PASS" if all(checks.values()) else "FAIL",
              "label": "host checks (static analysis of source text and ELF bytes)"}
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
