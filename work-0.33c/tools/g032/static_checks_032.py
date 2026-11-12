"""ABRAHAM 0.32 static checks (S21; design §4-§6, D-ABR-019). Host checks: text of the source and bytes of the ELFs.

  python -I -B tools/g032/static_checks_032.py <production ELF> <diag-svc-defects ELF> <out.json>

The 0.31b checks (one owner, no allocator, no dispatch) stay in tools/g031b/static_checks.py and are run as well.
These are the 0.32 additions:
  - no `unsafe` and no `static mut` in any service module (svc*.rs);
  - no `loop` or `while` in production service step code (svc_counter.rs);
  - nothing can set compromise: Compromise::Suspected / Compromise::Confirmed occur once each, in svcstatus.rs, only
    in `name()`; the PublicStatus compromise field is private;
  - no call site for the reserved manual reset (manual_reset / reviewed_operator_request) outside its definition;
  - the service modules do not read the event log; svcmgr.rs only records (eventlog::record) and prints once
    (eventlog::print_since, OptMs);
  - the service modules never call memory, paging, APIC, CPU, frame, page-walk or loader code;
  - the manager is reached only from main.rs (kmain and its loop), never from an interrupt path (cpu.rs, apic.rs);
  - every production and diagnostic table except DIAG_CYCLE is checked at compile time, and TABLE is PRODUCTION
    unless a diag-svc feature is set; Cargo.toml has no default features;
  - the production ELF contains `svc.counter` but no DIAGNOSTIC service name; the diag-svc-defects ELF contains
    `svc.diagliar` (positive control: the scan can find such a name); the production ELF has no allocator symbol.
"""
import json
import re
import sys
from pathlib import Path

W = Path(__file__).resolve().parents[2]
SRC = W / "kernel" / "src"
SVC = ["svcregistry.rs", "svclife.rs", "svcstatus.rs", "svcrun.rs", "svctable.rs", "svc_counter.rs", "svcmgr.rs", "svcdiag.rs"]
PURE = [f for f in SVC if f != "svcmgr.rs"]


def code_only(text):
    return "\n".join(l.split("//")[0] for l in text.splitlines())


def main():
    prod_elf, defects_elf, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    d, dd = prod_elf.read_bytes(), defects_elf.read_bytes()
    code = {p.name: code_only(p.read_text(encoding="utf-8")) for p in SRC.glob("*.rs")}
    svc = {f: code[f] for f in SVC}
    every = "\n".join(code.values())
    sus = [(f, m.start()) for f, c in code.items() for m in re.finditer(r"Compromise::Suspected", c)]
    conf = [(f, m.start()) for f, c in code.items() for m in re.finditer(r"Compromise::Confirmed", c)]
    status_src = code["svcstatus.rs"]
    name_fn = re.search(r"impl Compromise \{.*?pub const fn name\(self\) -> &'static str \{(?P<body>.*?)\n    \}\n\}", status_src, re.S)
    resets = [(f, l.strip()) for f, c in code.items() for l in c.splitlines()
              if ("manual_reset(" in l or "reviewed_operator_request(" in l) and "pub fn" not in l and "pub const fn" not in l]
    mgr_log = sorted(set(re.findall(r"eventlog::(\w+)", code["svcmgr.rs"])))
    cargo = (W / "kernel" / "Cargo.toml").read_text(encoding="utf-8")
    table = code["svctable.rs"]
    alloc_symbols = [b"__rust_alloc", b"__rg_alloc", b"__rdl_alloc", b"__rust_alloc_error_handler"]
    diag_names = [b"svc.diagcyc", b"svc.diagready", b"svc.diagliar", b"svc.diagdep", b"svc.diagslow", b"svc.diagstall",
                  b"svc.diagflaky", b"svc.diagdep2"]  # 0.32b adds the last two
    checks = {
        "no_unsafe_in_service_modules": not any(re.search(r"\bunsafe\b", c) for c in svc.values()),
        "no_static_mut_in_service_modules": not any(re.search(r"static\s+mut\b", c) for c in svc.values()),
        "no_loop_or_while_in_production_step_code": re.search(r"\b(loop|while)\b", code["svc_counter.rs"]) is None,
        "compromise_never_set": len(sus) == 1 and len(conf) == 1 and {sus[0][0], conf[0][0]} == {"svcstatus.rs"}
                                and name_fn is not None and "Compromise::Suspected" in name_fn["body"]
                                and "Compromise::Confirmed" in name_fn["body"],
        "compromise_field_private": re.search(r"pub\s+compromise\s*:", status_src) is None
                                    and re.search(r"\n    compromise: Compromise,", status_src) is not None,
        "no_manual_reset_call_site": not resets,
        "pure_service_modules_do_not_touch_the_log": not any(re.search(r"eventlog|events::|EventLog", svc[f]) for f in PURE),
        "manager_only_records_and_prints_once": set(mgr_log) <= {"record", "print_since", "OptMs", "self"},
        "services_do_not_call_low_level_code": not any(re.search(r"\b(memory|paging|apic|cpu|frame|ptwalk|limine)::", c)
                                                       for c in svc.values()),
        "manager_reached_only_from_main": [f for f, c in code.items() if "svcmgr::" in c] == ["main.rs"],
        "no_service_call_from_interrupt_code": not any("svc" in code[f] for f in ("cpu.rs", "apic.rs")),
        "tables_checked_at_compile_time": all(f"const _: () = assert_valid({n});" in table
                                              for n in ("PRODUCTION", "DIAG_DEFECTS", "DIAG_SLOW", "DIAG_STALL", "DIAG_CASCADE"))
                                          and "assert_valid(DIAG_CYCLE)" not in table,
        "production_table_is_the_default": re.search(r"#\[cfg\(not\(any\(feature = \"diag-svc-cycle\".*?\)\)\)\]\s*pub const TABLE: &\[Desc\] = PRODUCTION;",
                                                     table, re.S) is not None,
        "no_default_features": re.search(r"^\s*default\s*=", cargo, re.M) is None,
        "production_elf_has_counter": b"svc.counter" in d,
        "production_elf_has_no_diag_service": not any(n in d for n in diag_names),
        "control_defects_elf_has_diag_service": b"svc.diagliar" in dd,
        "production_elf_has_no_allocator_symbols": not any(s in d for s in alloc_symbols),
    }
    report = {"production_elf": str(prod_elf), "defects_elf": str(defects_elf), "checks": checks,
              "manager_eventlog_uses": mgr_log, "manual_reset_call_sites": resets,
              "verdict": "PASS" if all(checks.values()) else "FAIL",
              "label": "host checks (static analysis of source text and ELF bytes; not proofs)"}
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
