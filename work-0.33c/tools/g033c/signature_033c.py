"""ABRAHAM 0.33c Phase 4 (D-ABR-026): the ASCII-only MOSKO(TM) source signature, proven not to change the kernel.

  python -I -B tools/g033c/signature_033c.py --out evidence/phase4/ABR-0.33c-P4

Steps, each recorded:
  pre    build the DIAGNOSTIC launchpad and early-fail kernels in this workspace before any edit (the production
         rebuild before the edit is B001's, build/build-info.json: two identical builds);
  edit   prepend the signature as `//` comment lines to kernel/src/main.rs (the kernel's front-facing source, ahead of
         its `//!` description) and add it to README.md under its title. Only comments and documentation change;
  post   rebuild: `build.py repro` (two clean production builds) and the two DIAGNOSTIC builds;
  compare  post against pre byte for byte (same folder, same toolchain), and every post ELF's loaded sections against
         the TESTED binaries (6b95b9a2..., 89b3d6fa..., 79b6cdce...) with tools/g3/compare_sections.py;
  behave the signed production and launchpad builds booted once each under the official judges (WHPX): harness
         profile 0.33 (C0-C13), and launch_probe launchpad.
The signature adds no code, no boot output, no dependency, and changes no authorization or service contract: the
comparisons prove it. Standard library only.
"""
import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

C = Path(__file__).resolve().parents[2]
HOME = C.parent
PY = [sys.executable, "-I", "-B"]
QEMU = "C:/Users/XxUnd/abraham-toolchain/qemu/11.1.0-weil-20260811"
EFI = "third_party/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI"
TESTED = {"production": (HOME / "work-0.33/build/abraham-kernel-0.33.0-dev.elf", "6b95b9a27a8eedd68dd5023dbf99e73716aa1be88780ddde406099679e119a21"),
          "launchpad": (HOME / "work-0.33/build/diag/abraham-kernel-diag-launchpad.elf", "89b3d6fa186753f7539aa84e6cde19532e53ac00bd752255954105fcb7755758"),
          "early-fail": (HOME / "work-0.33/build/diag/abraham-kernel-diag-early-fail.elf", "79b6cdce89863073de71301e4b304014ddf651b95f123d8c2f43cd5b6f8e6409")}
SIGNATURE = [
    r" __  __    ___    ____    _  __   ___",
    r"|  \/  |  / _ \  / ___|  | |/ /  / _ \ ",
    r"| |\/| | | | | | \___ \  | ' /  | | | |",
    r"| |  | | | |_| |  ___) | | . \  | |_| |",
    r"|_|  |_|  \___/  |____/  |_|\_\  \___/  (TM)",
    "",
    "MOSKO(TM) - MOSKO Laboratory 001, Pripyat - Digital Front",
]
RS_BLOCK = "".join(("// " + l).rstrip() + "\n" for l in SIGNATURE) + \
    "// MOSKO(TM) source signature (D-ABR-026). Comment only: no code, no output, no dependency.\n\n"
MD_BLOCK = "```text\n" + "".join(l.rstrip() + "\n" for l in SIGNATURE) + "```\n\n"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(cmd, log):
    r = subprocess.run(cmd, cwd=C, capture_output=True, text=True)
    Path(log).write_text(r.stdout + ("\n--- stderr ---\n" + r.stderr if r.stderr else ""))
    return r.returncode


def compare(ref, cand, out):
    r = subprocess.run(PY + ["tools/g3/compare_sections.py", str(ref), str(cand)], cwd=C, capture_output=True, text=True)
    Path(out).write_text(r.stdout + r.stderr)
    try:
        return r.returncode, json.loads(r.stdout)["loaded_sections_identical"]
    except (ValueError, KeyError):
        return r.returncode, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    out = (C / ap.parse_args().out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    assert all(ord(ch) < 128 for ch in RS_BLOCK + MD_BLOCK), "the signature must be ASCII only"
    rec = {"started_utc": datetime.now(timezone.utc).isoformat(), "tested": {k: v[1] for k, v in TESTED.items()},
           "tested_present_and_matching": {k: sha(p) == d for k, (p, d) in TESTED.items()}}
    pre_info = json.loads((C / "build" / "build-info.json").read_text())
    rec["pre"] = {"production_repro_B001": pre_info.get("elf_sha256"), "production_repro_mode": pre_info.get("mode")}
    for feat, key in (("diag-launchpad", "launchpad"), ("diag-early-fail", "early-fail")):
        code = run(PY + ["tools/build.py", "diag", feat], out / f"pre-build-{feat}.txt")
        elf = C / "build" / "diag" / f"abraham-kernel-{feat}.elf"
        (out / "pre").mkdir(exist_ok=True)
        shutil.copyfile(elf, out / "pre" / elf.name)
        rec["pre"][key] = {"exit": code, "sha256": sha(elf)}
    # edit: comments and documentation only
    edits = {}
    for rel, block, where in (("kernel/src/main.rs", RS_BLOCK, "top"), ("README.md", MD_BLOCK, "after-title")):
        p = C / rel
        before = p.read_text(encoding="utf-8")
        if "MOSKO(TM) - MOSKO Laboratory 001" in before:
            raise SystemExit(f"REFUSED: {rel} already carries the signature")
        if where == "top":
            after = block + before
        else:
            first, rest = before.split("\n", 1)
            after = first + "\n\n" + block + rest.lstrip("\n")
        p.write_text(after, encoding="utf-8", newline="\n")
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "a/" + rel, "b/" + rel))
        (out / (Path(rel).name + ".diff")).write_text(diff, encoding="utf-8", newline="\n")
        removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
        added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
        edits[rel] = {"before_sha256": hashlib.sha256(before.encode()).hexdigest(), "after_sha256": sha(p),
                      "lines_removed": len(removed), "lines_added": len(added),
                      "only_comments_or_docs": rel.endswith(".md") or all(l == "" or l.startswith("//") for l in added)}
    rec["edits"] = edits
    # post builds
    rec["post"] = {}
    code = run(PY + ["tools/build.py", "repro"], out / "post-build-repro.txt")
    post_info = json.loads((C / "build" / "build-info.json").read_text())
    prod = C / "build" / "repro1" / "x86_64-unknown-none" / "release" / "abraham-kernel"
    (out / "post").mkdir(exist_ok=True)
    shutil.copyfile(prod, out / "post" / "abraham-kernel-0.33.0-dev-signed.elf")
    rec["post"]["production"] = {"exit": code, "repro": post_info.get("elf_sha256"), "result": post_info.get("result"),
                                 "sha256": sha(out / "post" / "abraham-kernel-0.33.0-dev-signed.elf")}
    for feat, key in (("diag-launchpad", "launchpad"), ("diag-early-fail", "early-fail")):
        code = run(PY + ["tools/build.py", "diag", feat], out / f"post-build-{feat}.txt")
        elf = C / "build" / "diag" / f"abraham-kernel-{feat}.elf"
        shutil.copyfile(elf, out / "post" / elf.name)
        rec["post"][key] = {"exit": code, "sha256": sha(elf)}
    # compare
    rec["compare"] = {}
    pre_prod = (rec["pre"]["production_repro_B001"] or [None])[0]
    rec["compare"]["production_post_equals_pre_bytes"] = rec["post"]["production"]["sha256"] == pre_prod
    rec["compare"]["production_two_post_builds_identical"] = len(set(rec["post"]["production"]["repro"] or [])) == 1
    for key in ("launchpad", "early-fail"):
        rec["compare"][f"{key}_post_equals_pre_bytes"] = rec["post"][key]["sha256"] == rec["pre"][key]["sha256"]
    for key, cand in (("production", out / "post" / "abraham-kernel-0.33.0-dev-signed.elf"),
                      ("launchpad", out / "post" / "abraham-kernel-diag-launchpad.elf"),
                      ("early-fail", out / "post" / "abraham-kernel-diag-early-fail.elf")):
        code, same = compare(TESTED[key][0], cand, out / f"sections-{key}-vs-tested.json")
        rec["compare"][f"{key}_loaded_sections_equal_tested"] = same is True and code == 0
    # behave
    b = {}
    p_elf, l_elf = out / "post" / "abraham-kernel-0.33.0-dev-signed.elf", out / "post" / "abraham-kernel-diag-launchpad.elf"
    b["production_C0_C13"] = run(PY + ["tools/abr_boot_001.py", "run", "--run-id", "ABR-0.33c-P4W1", "--kernel", str(p_elf),
                                       "--expect-kernel-sha256", sha(p_elf), "--qemu-dir", QEMU, "--limine-efi", EFI,
                                       "--accel", "whpx", "--profile", "0.33", "--restart", "cold"], out / "behave-production.txt")
    b["launchpad_17_requests"] = run(PY + ["tools/g033/launch_probe.py", "run", "--run-id", "ABR-0.33c-P4L1", "--qemu-dir", QEMU,
                                           "--accel", "whpx", "--kernel", str(l_elf), "--expect-kernel-sha256", sha(l_elf),
                                           "--limine-efi", EFI, "--expect", "launchpad", "--seconds", "12"], out / "behave-launchpad.txt")
    final = json.loads((C / "evidence" / "ABR-BOOT-001" / "ABR-0.33c-P4W1" / "results.json.final").read_text())
    probe = json.loads((C / "evidence" / "g033" / "ABR-0.33c-P4L1" / "result.json").read_text())
    rec["behave"] = {"exits": b, "production_verdict": final["verdict"], "launchpad_verdict": probe["verdict"],
                     "production_failed": sorted(k for k, v in final["conditions"].items() if v.get("pass") is False)}
    ok = (all(rec["tested_present_and_matching"].values()) and all(e["only_comments_or_docs"] for e in edits.values())
          and all(rec["compare"].values()) and final["verdict"] == "PASS" and probe["verdict"] == "PASS")
    rec["verdict"] = "SIGNATURE CHANGES NO BINARY" if ok else "NOT SHOWN"
    rec["ended_utc"] = datetime.now(timezone.utc).isoformat()
    (out / "signature.json").write_text(json.dumps(rec, indent=1) + "\n")
    sums = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    (out / "RUN_SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"verdict": rec["verdict"], "compare": rec["compare"], "behave": rec["behave"], "edits": edits}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
