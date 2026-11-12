"""ABRAHAM 0.33 static checks (host checks on the sources and the built binaries; design §8, §11).

  python -I -B tools/g033/static_checks_033.py <production ELF> <diag-launchpad ELF> <out.json>

Every check must hold:
  S1  ExecutionEvidence is constructed nowhere: the only `ExecutionEvidence {` in kernel/src is its definition.
  S2  `enum Executor` has exactly one variant, Absent.
  S3  the production application table names only `ExecSupport::None`.
  S4  no application descriptor carries an authority field: AppDesc's fields are exactly id, name, kind, revision,
      requires, exec.
  S5  the launcher holds the services only by shared reference: launch.rs and launchpad.rs never take
      `&mut ServiceSet` and never call start_all / step_all / request.
  S6  there is no input path: no serial read, port input (`inb`, `in al`) or keyboard code in the launcher files.
  S7  the production ELF contains the discovery line tags (ABR|APP|registry=, ABR|APPINFO) and NOT the request-path
      tags (ABR|LAUNCHRESULT, ABR|LAUNCHPAD, ABR|APPQUERY): a production kernel cannot even print a launch result.
  S8  the diag-launchpad ELF does contain the request-path tags (so S7 is not vacuous).
  S9  no new event kind: events.rs is byte-identical to the accepted 0.32b events.rs.
  S10 the 27 Appendix A names do not occur as string literals in any 0.33 launcher file.
Standard library only. Writes only <out.json>.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

W = Path(__file__).resolve().parents[2]
HOME = W.parent
SRC = W / "kernel" / "src"
LAUNCHER = ["appregistry.rs", "apptable.rs", "launchreq.rs", "launchlife.rs", "launch.rs", "launchpad.rs"]


def read(n):
    return (SRC / n).read_text(encoding="utf-8")


def main():
    prod, diag, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    pb, db = prod.read_bytes(), diag.read_bytes()
    all_src = {p.name: p.read_text(encoding="utf-8") for p in SRC.glob("*.rs")}
    constructs = [(n, m.start()) for n, t in all_src.items() for m in re.finditer(r"ExecutionEvidence\s*\{", t)]
    executor = re.search(r"pub enum Executor \{(?P<body>[^}]*)\}", read("appregistry.rs"))
    variants = [v.strip().rstrip(",") for v in executor["body"].split("\n") if v.strip() and not v.strip().startswith("//")] if executor else []
    prod_table = read("apptable.rs").split("pub const PRODUCTION")[0]
    prod_consts = re.findall(r"const (COUNTERVIEW|NETSTATUS|BROWSER): AppDesc = AppDesc \{[^;]*?exec: (ExecSupport::\w+)", prod_table, re.S)
    desc = re.search(r"pub struct AppDesc \{(?P<body>.*?)\n\}", read("appregistry.rs"), re.S)
    fields = re.findall(r"pub (\w+):", desc["body"]) if desc else []
    lp = read("launch.rs") + read("launchpad.rs")
    appendix = re.findall(r"^\| `([A-Z_]+)` \|", (HOME / "ABRAHAM_0.2_BASELINE.md").read_text(encoding="utf-8").split("## Appendix A")[1]
                          .split("## Appendix B")[0], re.M)
    literal_public = sorted({c for n in LAUNCHER for c in appendix if f'"{c}"' in read(n)})
    events_now = hashlib.sha256((SRC / "events.rs").read_bytes()).hexdigest()
    events_032b = hashlib.sha256((HOME / "work-0.32b" / "kernel" / "src" / "events.rs").read_bytes()).hexdigest()
    checks = {
        "S1_execution_evidence_never_constructed": [n for n, _ in constructs] == ["launchlife.rs"]
                                                   and "pub struct ExecutionEvidence {" in read("launchlife.rs"),
        "S2_executor_has_only_absent": variants == ["Absent"],
        "S3_production_table_exec_none_only": sorted(c for c, _ in prod_consts) == ["BROWSER", "COUNTERVIEW", "NETSTATUS"]
                                              and all(e == "ExecSupport::None" for _, e in prod_consts),
        "S4_descriptor_has_no_authority_field": fields == ["id", "name", "kind", "revision", "requires", "exec"],
        "S5_services_only_by_shared_reference": "&mut ServiceSet" not in lp
                                                and not re.search(r"\.(start_all|step_all|request)\(", lp),
        "S6_no_input_path": not any(re.search(r"\binb\b|in al|read_byte|keyboard|recv", read(n)) for n in LAUNCHER),
        "S7_production_binary_has_no_request_path": b"ABR|APP|registry=" in pb and b"ABR|APPINFO|" in pb
                                                    and not any(t in pb for t in (b"ABR|LAUNCHRESULT", b"ABR|LAUNCHPAD", b"ABR|APPQUERY")),
        "S8_diag_binary_has_the_request_path": all(t in db for t in (b"ABR|LAUNCHRESULT", b"ABR|LAUNCHPAD", b"ABR|APPQUERY")),
        "S9_no_new_event_kind": events_now == events_032b,
        "S10_no_appendix_a_literal_in_launcher_files": len(appendix) == 27 and not literal_public,
    }
    rep = {"label": "host checks (sources and binaries)", "production_elf": str(prod),
           "production_elf_sha256": hashlib.sha256(pb).hexdigest(), "diag_elf": str(diag),
           "diag_elf_sha256": hashlib.sha256(db).hexdigest(), "checks": checks,
           "details": {"execution_evidence_braces": constructs, "executor_variants": variants, "descriptor_fields": fields,
                       "appendix_a_literals_in_launcher_files": literal_public, "events_rs": [events_now, events_032b]},
           "verdict": "PASS" if all(checks.values()) else "FAIL"}
    out.write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps({"verdict": rep["verdict"], "failed": [k for k, v in checks.items() if not v]}, indent=1))
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
