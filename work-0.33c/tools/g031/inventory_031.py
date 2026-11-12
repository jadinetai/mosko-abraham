"""ABRAHAM 0.31a Step 1: read-only source and environment inventory.

Re-verifies the accepted state before any 0.3 work:
  - frozen ABR-BOOT-001 snapshot (manifest digest, every file)
  - 0.29 sign-off index (digest, every entry; append-only docs checked as whole-line prefixes)
  - every run seal listed in the sign-off index (members re-hashed)
  - kernel binaries, Limine, firmware, audit archive
  - toolchain versions and pinned QEMU executables
Writes nothing except its JSON report to the path given as argv[1].
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
FREEZE = HOME / "frozen" / "ABR-BOOT-001-accepted"
WORK = HOME / "work-0.29"
TOOLCHAIN = Path(r"C:\Users\XxUnd\abraham-toolchain")

EXPECT = {
    "freeze_manifest": "9085367e5036480cdb4904ae28e3e34469453d9a3ddf3e2088281d1ea16dd6a8",
    "signoff_index": "98d15717b35790435ef46fbb34aec5abbbbf25d0f7e151af0dde1b1184e3449f",
    "kernel_029": "ef751eafc3bceb7e2f8d9bd1e27a50f91824cb10bff8872856e9485e2f341f4e",
    "kernel_frozen": "5c2e7700acbfde783e54871b28fed843863be7510cfbcf8a04bb2673b017caa2",
    "limine_bootx64": "e486ae7abd7d5b88f98f43cfd6e8f9057ff975ecd667dfb33f1581de36e00982",
    "edk2_code": "33090cc07675baa5190d9f1e84bf5176b33bcbfa9bacac522961150cdb6dbb2a",
    "edk2_vars": "5d2ac383371b408398accee7ec27c8c09ea5b74a0de0ceea6513388b15be5d1e",
    "qemu_1110_exe": "47d57a6072e0bb3bd98f87926eb129eb1736dfe818c67b3b81ef7ce4edd0b3cd",
    "audit_zip": "076a6b71daf2a5c80f5215fe359157f2e61988918b8c6bd360488eb9c97aa9b4",
}
APPEND_ONLY = {"DECISIONS.md", "test-records\\INDEX.md"}


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha(p):
    return sha_bytes(Path(p).read_bytes())


def resolve(rel):
    p = Path(rel)
    return p if p.is_absolute() else HOME / rel


def prefix_match(path, digest):
    """True if some whole-line prefix of the file hashes to digest (append-only check)."""
    data = path.read_bytes()
    if sha_bytes(data) == digest:
        return "EXACT"
    idx = 0
    while True:
        idx = data.find(b"\n", idx)
        if idx < 0:
            return None
        idx += 1
        if sha_bytes(data[:idx]) == digest:
            return f"PREFIX({idx} of {len(data)} bytes)"


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr).strip().splitlines()[0] if (r.stdout + r.stderr).strip() else f"exit {r.returncode}"
    except Exception as e:  # noqa: BLE001
        return f"UNAVAILABLE: {e}"


out = {"checks": {}, "fail": []}


def check(name, ok, detail):
    out["checks"][name] = {"ok": bool(ok), "detail": detail}
    if not ok:
        out["fail"].append(name)


# 1. Freeze
mf = FREEZE / "FREEZE_MANIFEST.sha256"
check("freeze.manifest_digest", sha(mf) == EXPECT["freeze_manifest"], sha(mf))
manifest = dict((l.split("  ", 1)[1], l.split("  ", 1)[0]) for l in mf.read_text().splitlines())
on_disk = {p.relative_to(FREEZE).as_posix() for p in FREEZE.rglob("*") if p.is_file()} - {"FREEZE_MANIFEST.sha256", "FREEZE.md"}
mism = [k for k, v in manifest.items() if not (FREEZE / k).is_file() or sha(FREEZE / k) != v]
check("freeze.files", not mism and on_disk == set(manifest),
      {"entries": len(manifest), "mismatch": mism, "unlisted": sorted(on_disk - set(manifest)),
       "missing": sorted(set(manifest) - on_disk)})
ro = [p.relative_to(FREEZE).as_posix() for p in FREEZE.rglob("*") if p.is_file() and (p.stat().st_file_attributes & 1) == 0]
check("freeze.readonly_attribute", not ro, {"not_readonly": ro})

# 2. Sign-off index
si = WORK / "EVIDENCE_INDEX_0.29_SIGNOFF.sha256"
check("signoff.index_digest", sha(si) == EXPECT["signoff_index"], sha(si))
entries = [l.split("  ") for l in si.read_text().splitlines() if l.strip()]
per_kind, bad, notes, seals = {}, [], {}, {"runs": 0, "members": 0, "mismatch": []}
for digest, kind, rel in entries:
    p = resolve(rel)
    per_kind[kind] = per_kind.get(kind, 0) + 1
    if not p.is_file():
        bad.append(("MISSING", rel))
        continue
    if rel in APPEND_ONLY:
        m = prefix_match(p, digest)
        notes[rel] = m
        if not m:
            bad.append(("NOT_A_PREFIX", rel))
        continue
    if sha(p) != digest:
        bad.append(("MISMATCH", rel))
    if kind == "run-seal":
        seals["runs"] += 1
        for name, v in json.loads(p.read_text()).items():
            seals["members"] += 1
            f = p.parent / name
            if not f.is_file() or sha(f) != v:
                seals["mismatch"].append(f"{p.parent.name}/{name}")
check("signoff.entries", not bad, {"entries": len(entries), "per_kind": per_kind, "bad": bad, "append_only": notes})
check("signoff.run_seal_members", not seals["mismatch"], seals)

# 3. Key binaries
check("kernel.029_elf", sha(WORK / "build/abraham-kernel-0.1.1.elf") == EXPECT["kernel_029"], sha(WORK / "build/abraham-kernel-0.1.1.elf"))
check("kernel.frozen_copy_in_work", sha(WORK / "build/abraham-kernel.elf") == EXPECT["kernel_frozen"], sha(WORK / "build/abraham-kernel.elf"))
bi = json.loads((WORK / "build/build-info.json").read_text())
src_now = {k: sha(WORK / k) for k in bi["inputs"]}
check("kernel.029_sources_equal_build_inputs", src_now == bi["inputs"], {k: v == bi["inputs"][k] for k, v in src_now.items()})
check("limine.bootx64_frozen", sha(FREEZE / "loader/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI") == EXPECT["limine_bootx64"], "frozen loader copy")
check("firmware.code_frozen", sha(FREEZE / "platform/accepted-firmware/edk2-x86_64-code.fd") == EXPECT["edk2_code"], "frozen")
check("firmware.vars_frozen", sha(FREEZE / "platform/accepted-firmware/edk2-i386-vars.fd") == EXPECT["edk2_vars"], "frozen")
check("audit_zip", sha(HOME / "ABRAHAM_0.29_ECHO_AUDIT.zip") == EXPECT["audit_zip"], sha(HOME / "ABRAHAM_0.29_ECHO_AUDIT.zip"))

# 4. Toolchain
q = TOOLCHAIN / "qemu" / "11.1.0-weil-20260811"
qexe = q / "qemu-system-x86_64.exe"
check("qemu.1110_exe", qexe.is_file() and sha(qexe) == EXPECT["qemu_1110_exe"], str(qexe))
fw = q / "share" / "edk2-x86_64-code.fd"
check("qemu.1110_firmware_equals_accepted", fw.is_file() and sha(fw) == EXPECT["edk2_code"], str(fw))
filelist = TOOLCHAIN / "qemu" / "11.1.0-weil-20260811.files.sha256"
fl_bad, fl_n = [], 0
for line in filelist.read_text().splitlines():
    if not line.strip():
        continue
    d, rel = line.split("  ", 1)
    fl_n += 1
    f = q / rel
    if not f.is_file() or sha(f) != d:
        fl_bad.append(rel)
check("qemu.1110_tree_matches_pin", not fl_bad, {"files": fl_n, "mismatch": fl_bad[:20], "mismatch_count": len(fl_bad)})
out["toolchain"] = {
    "rustc": run(["rustc", "-V"]),
    "cargo": run(["cargo", "-V"]),
    "targets": run(["rustup", "target", "list", "--installed"]),
    "nasm": run([r"C:\Program Files\NASM\nasm.exe", "-v"]),
    "qemu_1110": run([str(qexe), "--version"]),
    "python": sys.version.split()[0],
    "git": run(["git", "--version"]),
}
r = subprocess.run(["rustup", "target", "list", "--installed"], capture_output=True, text=True)
out["toolchain"]["targets"] = r.stdout.split()
check("toolchain.rust_target", "x86_64-unknown-none" in out["toolchain"]["targets"], out["toolchain"]["targets"])
check("toolchain.rustc_version", out["toolchain"]["rustc"].startswith("rustc 1.99.1"), out["toolchain"]["rustc"])
check("toolchain.nasm_version", out["toolchain"]["nasm"].startswith("NASM version 3.02"), out["toolchain"]["nasm"])

# 5. Work-tree source digests (baseline for the 0.31 copy)
out["work_029_source"] = {p.relative_to(WORK).as_posix(): sha(p) for d in ("kernel", "boot", "tools", "docs")
                         for p in sorted((WORK / d).rglob("*")) if p.is_file() and "target" not in p.parts and "__pycache__" not in p.parts}
out["work_029_root"] = {p.name: sha(p) for p in sorted(WORK.iterdir()) if p.is_file()}

out["verdict"] = "INVENTORY VERIFIED" if not out["fail"] else "INVENTORY DISCREPANCY"
Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
print(out["verdict"], "fail:", out["fail"])
for k, v in out["checks"].items():
    print(("OK  " if v["ok"] else "FAIL"), k)
print(json.dumps(out["toolchain"], indent=1))
sys.exit(0 if not out["fail"] else 1)
