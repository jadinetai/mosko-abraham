"""Independent read-only verification of the frozen ABR-BOOT-001 snapshot."""
import hashlib
import json
import sys
from pathlib import Path

FREEZE = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham\frozen\ABR-BOOT-001-accepted")
HOME = Path(r"C:\Users\XxUnd\OneDrive\Documents\Abraham")
EXPECT = {
    "build/abraham-kernel.elf": "5c2e7700acbfde783e54871b28fed843863be7510cfbcf8a04bb2673b017caa2",
    "loader/limine-12.9.6/extracted/limine-binary/BOOTX64.EFI": "e486ae7abd7d5b88f98f43cfd6e8f9057ff975ecd667dfb33f1581de36e00982",
    "platform/accepted-firmware/edk2-x86_64-code.fd": "33090cc07675baa5190d9f1e84bf5176b33bcbfa9bacac522961150cdb6dbb2a",
    "platform/accepted-firmware/edk2-i386-vars.fd": "5d2ac383371b408398accee7ec27c8c09ea5b74a0de0ceea6513388b15be5d1e",
    "loader/limine-12.9.6/download/limine-binary.zip": "d7aa69bae2cab18d2fc2ff0fdf0af8b8c8724c1be4b9460b69df774aac5c758d",
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


out = {}
manifest = dict((l.split("  ", 1)[1], l.split("  ", 1)[0]) for l in (FREEZE / "FREEZE_MANIFEST.sha256").read_text().splitlines())
on_disk = {p.relative_to(FREEZE).as_posix() for p in FREEZE.rglob("*") if p.is_file()} - {"FREEZE_MANIFEST.sha256", "FREEZE.md"}
out["manifest_entries"] = len(manifest)
out["manifest_mismatch"] = [k for k, v in manifest.items() if sha(FREEZE / k) != v]
out["unlisted_files"] = sorted(on_disk - set(manifest))
out["listed_missing"] = sorted(set(manifest) - on_disk)
out["accepted_digests"] = {k: sha(FREEZE / k) == v for k, v in EXPECT.items()}
seals = {}
for run_dir in sorted((FREEZE / "evidence").glob("*/*")):
    s = run_dir / "RUN_SHA256SUMS.json"
    if s.is_file():
        sums = json.loads(s.read_text())
        seals[run_dir.name] = "OK" if all(sha(run_dir / n) == v for n, v in sums.items()) else "MISMATCH"
out["run_seals_in_freeze"] = seals
reloc = json.loads((HOME / "RELOCATION_2026-11-01.manifest.json").read_text())["copied"]
mapping = {"os/kernel/": "source/kernel/", "os/boot/": "source/boot/", "os/tools/": "source/tools/",
           "os/evidence/": "evidence/", "os/third_party/limine-12.9.6/": "loader/limine-12.9.6/"}
checked, bad = 0, []
for rel, digest in reloc.items():
    for a, b in mapping.items():
        if rel.startswith(a):
            checked += 1
            target = FREEZE / (b + rel[len(a):])
            if not target.is_file() or sha(target) != digest:
                bad.append(rel)
out["relocation_manifest_cross_check"] = {"checked": checked, "mismatch": bad}
print(json.dumps(out, indent=1))
sys.exit(1 if out["manifest_mismatch"] or out["listed_missing"] or bad or not all(out["accepted_digests"].values())
         or "MISMATCH" in seals.values() else 0)
