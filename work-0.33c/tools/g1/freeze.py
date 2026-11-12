"""G1: build the frozen ABR-BOOT-001 reference snapshot. Copies only; never edits a source.
Writes FREEZE_MANIFEST.sha256 (full SHA-256 of every frozen file) and verifies each copy."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
ORIG = Path(r"C:\Users\XxUnd\.codex\.chatgpt-projects\g-p-6aa407aba63081918d661ca0cf9a434d\daemons\abraham")
QEMU = Path(r"C:\Program Files\qemu")
FREEZE = HOME / "frozen" / "ABR-BOOT-001-accepted"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


plan = []  # (source, destination relative to FREEZE)


def add_tree(src, dst, skip=()):
    for p in sorted(Path(src).rglob("*")):
        rel = p.relative_to(src)
        if p.is_file() and "__pycache__" not in rel.parts and not any(rel.parts[0] == s for s in skip):
            plan.append((p, Path(dst) / rel))


def add(src, dst):
    plan.append((Path(src), Path(dst)))


# Source as booted (kernel inputs verified against R002's recorded build inputs).
add_tree(HOME / "os/kernel", "source/kernel")
add_tree(HOME / "os/boot", "source/boot")
add_tree(HOME / "os/tools", "source/tools")
add_tree(HOME / "os/docs", "source/docs")
add(HOME / "os/README.md", "source/README.md")
# Accepted build products: from the original tree (the home copies were regenerated on 2026-11-01).
add(ORIG / "os/build/abraham-kernel.elf", "build/abraham-kernel.elf")
add(ORIG / "os/build/entry.o", "build/entry.o")
add(ORIG / "os/build/build-info.json", "build/build-info.json")
add(ORIG / "os/build/source-manifest-TR-0013.sha256", "build/source-manifest-TR-0013.sha256")
for name in ("R001.console.txt", "R002.console.txt", "ABR-BOOT-001-R003.console.txt",
             "ABR-BOOT-001-R004.console.txt", "N001.console.txt"):
    add(ORIG / "os/build" / name, f"build/console/{name}")
# Loader: binary release, signature, key, verification output, docs actually read.
add_tree(HOME / "os/third_party/limine-12.9.6", "loader/limine-12.9.6")
# Firmware of the accepted configuration: still byte-identical to R002's recorded inputs.
R002 = json.loads((HOME / "os/evidence/ABR-BOOT-001/ABR-BOOT-001-R002/host.json").read_text())
for key, name in (("firmware_code", "edk2-x86_64-code.fd"), ("firmware_vars_template", "edk2-i386-vars.fd")):
    if sha(QEMU / "share" / name) != R002["inputs"][key]["sha256"]:
        raise SystemExit(f"FIRMWARE CHANGED since R002: {name}")
    add(QEMU / "share" / name, f"platform/accepted-firmware/{name}")
add(QEMU / "share/edk2-licenses.txt", "platform/accepted-firmware/edk2-licenses.txt")
# All ABR-BOOT-001 evidence (R002/R003 are the counted runs), diagnostics and self-tests.
add_tree(HOME / "os/evidence", "evidence")
# Records and decisions.
add(HOME / "test-records/TR-0013.md", "records/TR-0013.md")
add(HOME / "test-records/INDEX.md", "records/INDEX.md")
add(HOME / "DECISIONS.md", "records/DECISIONS.md")
add(HOME / "ABRAHAM_0.2_BASELINE.md", "records/ABRAHAM_0.2_BASELINE.md")
for name in ("RELOCATION_2026-11-01.md", "RELOCATION_2026-11-01.manifest.json",
             "RELOCATION_2026-11-01.daemons-source.sha256", "RELOCATION_2026-11-01.preexisting.sha256"):
    add(HOME / name, f"records/{name}")

if FREEZE.exists():
    raise SystemExit(f"REFUSED: {FREEZE} exists")
manifest = {}
for src, rel in plan:
    dst = FREEZE / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if sha(dst) != sha(src):
        raise SystemExit(f"COPY MISMATCH {rel}")
    manifest[rel.as_posix()] = sha(dst)

version = subprocess.run([str(QEMU / "qemu-system-x86_64.exe"), "--version"], capture_output=True, text=True).stdout
platform = {
    "accepted_configuration": {
        "qemu_version_as_recorded_by_every_accepted_run": R002["qemu"],
        "qemu_executable_sha256": "NOT RECORDED at the time (gap in TR-0013)",
        "firmware_code_sha256": R002["inputs"]["firmware_code"]["sha256"],
        "firmware_vars_template_sha256": R002["inputs"]["firmware_vars_template"]["sha256"],
        "machine": "q35, -accel whpx -cpu host, -smp 1, -m 256 (from R002 host.json qemu_command)",
    },
    "installation_present_at_freeze_time": {
        "path": str(QEMU / "qemu-system-x86_64.exe"),
        "qemu_executable_sha256": sha(QEMU / "qemu-system-x86_64.exe"),
        "qemu_version_output": version.strip(),
        "is_accepted_binary": False,
        "replaced_at": "qemu-uninstall.exe last written 2026-11-01 18:22 local (EST) = 23:22 UTC, "
                       "after N001 (22:45 UTC); not done by Claude",
        "firmware_identical_to_accepted": True,
    },
}
pf = FREEZE / "platform/PLATFORM.json"
pf.write_text(json.dumps(platform, indent=1) + "\n")
manifest["platform/PLATFORM.json"] = sha(pf)

lines = "".join(f"{v}  {k}\n" for k, v in sorted(manifest.items()))
(FREEZE / "FREEZE_MANIFEST.sha256").write_text(lines, newline="\n")
print(json.dumps({"files": len(manifest), "manifest_sha256": sha(FREEZE / "FREEZE_MANIFEST.sha256"),
                  "platform": platform}, indent=1))
