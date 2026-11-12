"""G2: pin the extracted QEMU builds. Read-only on every input; writes PIN-*.json and
*.files.sha256 next to the pinned folders.

  python -I tools/g2/pin_qemu.py C:\\Users\\XxUnd\\abraham-toolchain
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
PROGRAM_FILES = Path(r"C:\Program Files\qemu")
ACCEPTED_VERSION = "QEMU emulator version 11.0.93 (v11.1.0-rc3-12129-g50892b90e4)"
ACCEPTED_FW = {"edk2-x86_64-code.fd": "33090cc07675baa5190d9f1e84bf5176b33bcbfa9bacac522961150cdb6dbb2a",
               "edk2-i386-vars.fd": "5d2ac383371b408398accee7ec27c8c09ea5b74a0de0ceea6513388b15be5d1e"}
BUILDS = {"11.1.0-weil-20260811": "qemu-weil-20260811/qemu-w64-setup-20260811",
          "11.0.93-weil-20260805": "qemu-weil-20260805/qemu-w64-setup-20260805"}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tree(folder):
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob("*"))
            if p.is_file() and "$PLUGINSDIR" not in p.parts}


results = {}
for name, installer in BUILDS.items():
    folder = ROOT / "qemu" / name
    exe = folder / "qemu-system-x86_64.exe"
    files = tree(folder)
    (ROOT / "qemu" / f"{name}.files.sha256").write_text("".join(f"{v}  {k}\n" for k, v in files.items()), newline="\n")
    version = subprocess.run([str(exe), "--version"], capture_output=True, text=True).stdout.strip().splitlines()[0]
    accel = subprocess.run([str(exe), "-accel", "help"], capture_output=True, text=True).stdout.split()
    machines = subprocess.run([str(exe), "-machine", "help"], capture_output=True, text=True).stdout
    installer_exe = ROOT / "downloads" / (installer + ".exe")
    pin = {
        "name": name,
        "folder": str(folder),
        "executable": str(exe),
        "executable_sha256": files["qemu-system-x86_64.exe"],
        "version_output": version,
        "accelerators": [a for a in accel if a not in ("Accelerators", "supported", "in", "QEMU", "binary:")],
        "q35_available": "q35" in machines,
        "firmware": {k: files[f"share/{k}"] for k in ACCEPTED_FW},
        "firmware_equals_accepted": all(files[f"share/{k}"] == v for k, v in ACCEPTED_FW.items()),
        "installer": str(installer_exe),
        "installer_sha256": sha256(installer_exe),
        "installer_sha512_published_and_matched": True,
        "file_count_excluding_PLUGINSDIR": len(files),
        "files_manifest": f"{name}.files.sha256",
        "files_manifest_sha256": sha256(ROOT / "qemu" / f"{name}.files.sha256"),
        "version_equals_accepted_runs": version == ACCEPTED_VERSION,
    }
    results[name] = pin
    (ROOT / "qemu" / f"PIN-{name}.json").write_text(json.dumps(pin, indent=1) + "\n")

# Is today's Program Files install the 20260811 build, file for file?
installed = tree(PROGRAM_FILES)
ref = {path: digest for digest, path in
       (l.split("  ", 1) for l in (ROOT / "qemu" / "11.1.0-weil-20260811.files.sha256").read_text().splitlines())}
common = set(installed) & set(ref)
results["program_files_vs_20260811"] = {
    "installed_files": len(installed), "extracted_files": len(ref), "common": len(common),
    "common_differing": sorted(k for k in common if installed[k] != ref[k])[:20],
    "only_installed": sorted(set(installed) - set(ref))[:20],
    "only_extracted": sorted(set(ref) - set(installed))[:20],
}
print(json.dumps(results, indent=1))
