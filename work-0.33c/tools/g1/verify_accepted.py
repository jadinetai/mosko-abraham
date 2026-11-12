"""G1 pre-freeze verification (read-only). Full SHA-256 everywhere."""
import hashlib
import json
from pathlib import Path

HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
ORIG = Path(r"C:\Users\XxUnd\.codex\.chatgpt-projects\g-p-6aa407aba63081918d661ca0cf9a434d\daemons\abraham")
ACCEPTED_KERNEL = "5c2e7700acbfde783e54871b28fed843863be7510cfbcf8a04bb2673b017caa2"
ACCEPTED_LIMINE = "e486ae7abd7d5b88f98f43cfd6e8f9057ff975ecd667dfb33f1581de36e00982"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


report = {}

# 1. Run seals: every sealed file re-hashed; list files present but not sealed.
for run in ("R001", "R002", "R003", "R004", "N001"):
    d = HOME / "os" / "evidence" / "ABR-BOOT-001" / f"ABR-BOOT-001-{run}"
    sums = json.loads((d / "RUN_SHA256SUMS.json").read_text())
    bad = [n for n, v in sums.items() if sha(d / n) != v]
    present = {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()}
    report[run] = {"sealed": len(sums), "mismatch": bad,
                   "unsealed": sorted(present - set(sums) - {"RUN_SHA256SUMS.json"}),
                   "kernel_in_host_json": json.loads((d / "host.json").read_text())["inputs"].get("kernel_elf", {}).get("sha256")}

# 2. Source manifest made at TR-0013 time (paths relative to os/).
manifest = HOME / "os" / "build" / "source-manifest-TR-0013.sha256"
src_bad = []
for line in manifest.read_text().splitlines():
    digest, name = line.split(maxsplit=1)
    name = name.lstrip("*")
    if sha(HOME / "os" / name) != digest:
        src_bad.append(name)
report["source_manifest_TR-0013"] = {"entries": len(manifest.read_text().splitlines()), "differ_now": src_bad}

# 3. Kernel inputs as recorded inside R002's host.json (the build that was booted).
r2 = json.loads((HOME / "os/evidence/ABR-BOOT-001/ABR-BOOT-001-R002/host.json").read_text())
bi = r2.get("build_info", {})
inputs_bad = [k for k, v in bi.get("inputs", {}).items() if sha(HOME / "os" / k) != v]
report["R002_recorded_build_inputs"] = {"count": len(bi.get("inputs", {})), "differ_now": inputs_bad,
                                        "build_info_mode": bi.get("mode"), "elf_sha256": bi.get("elf_sha256")}

# 4. Accepted binaries.
report["kernel_elf"] = sha(HOME / "os/build/abraham-kernel.elf") == ACCEPTED_KERNEL
report["limine_efi"] = sha(HOME / "os/third_party/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI") == ACCEPTED_LIMINE
report["kernel_elf_in_R002_esp"] = sha(HOME / "os/evidence/ABR-BOOT-001/ABR-BOOT-001-R002/esp/boot/abraham-kernel") == ACCEPTED_KERNEL

# 5. Home vs daemons original for everything under os/ that exists in both.
diff = []
for p in sorted((ORIG / "os").rglob("*")):
    if p.is_file():
        q = HOME / "os" / p.relative_to(ORIG / "os")
        if q.is_file() and sha(p) != sha(q):
            diff.append(p.relative_to(ORIG).as_posix())
report["home_vs_daemons_differ"] = diff
report["daemons_build_info"] = json.loads((ORIG / "os/build/build-info.json").read_text()).get("elf_sha256")
print(json.dumps(report, indent=1))
