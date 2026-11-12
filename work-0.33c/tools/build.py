"""Build the Abraham kernel (ABR-BOOT-001). Standard library only.

  python tools/build.py precheck   compile-only validation with the installed toolchain:
                                   NASM assembles entry.asm; rustc compiles the kernel
                                   crate to an object for x86_64-unknown-linux-musl.
                                   That object is never linked or booted (red zone, SSE).
  python tools/build.py kernel     the real build: x86_64-unknown-none, linked by rust-lld
                                   with kernel/linker.ld -> build/abraham-kernel.elf
  python tools/build.py repro      two clean kernel builds in separate target dirs; the
                                   ELF SHA-256 must be identical

Writes build/build-info.json (tool versions, input and output digests) on every mode.
No network access; a missing Rust target is reported, never installed.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

OS = Path(__file__).resolve().parents[1]
KERNEL = OS / "kernel"
BUILD = OS / "build"
TARGET = "x86_64-unknown-none"
CHECK_TARGET = "x86_64-unknown-linux-musl"
NASM_DIRS = [Path(r"C:\Program Files\NASM")]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tool(name):
    found = shutil.which(name)
    if found:
        return found
    for directory in NASM_DIRS:
        candidate = directory / (name + ".exe")
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(f"BLOCKED: {name} not found")


def version(command):
    try:
        return subprocess.run(command, capture_output=True, text=True).stdout.strip().splitlines()[0]
    except (OSError, IndexError):
        return "UNAVAILABLE"


def run(command, env=None):
    print("+", " ".join(str(c) for c in command), flush=True)
    result = subprocess.run(command, env=env)
    return result.returncode


def inputs():
    files = sorted(p for p in KERNEL.rglob("*") if p.is_file() and "target" not in p.parts)
    return {p.relative_to(OS).as_posix(): sha256(p) for p in files}


def installed_targets():
    out = subprocess.run(["rustup", "target", "list", "--installed"], capture_output=True, text=True).stdout
    return out.split()


def assemble():
    BUILD.mkdir(exist_ok=True)
    obj = BUILD / "entry.o"
    # All warnings are errors, except the two relocation classes that every linked kernel
    # has by design (references between .text, .rodata and .bss, resolved by rust-lld).
    rc = run([tool("nasm"), "-f", "elf64", "-w+all", "-w-reloc-rel-dword", "-w-reloc-abs-qword",
              "-Werror", "-o", obj, KERNEL / "asm" / "entry.asm"])
    if rc:
        raise SystemExit(f"FAIL: nasm exit {rc}")
    return obj


def rustflags(entry_obj):
    flags = [
        "-Ccode-model=kernel",
        "-Crelocation-model=static",
        f"-Clink-arg=-T{KERNEL / 'linker.ld'}",
        f"-Clink-arg={entry_obj}",
        "-Clink-arg=-zmax-page-size=0x1000",
        "-Clink-arg=--build-id=none",
        f"--remap-path-prefix={OS}=/abraham",
    ]
    return "\x1f".join(flags)


def kernel_build(target_dir, features=()):
    if TARGET not in installed_targets():
        raise SystemExit(f"BLOCKED: Rust target {TARGET} is not installed "
                         f"(needs: rustup target add {TARGET}, operator approval required)")
    entry = assemble()
    env = dict(os.environ, CARGO_TARGET_DIR=str(target_dir), CARGO_ENCODED_RUSTFLAGS=rustflags(entry))
    env.pop("RUSTFLAGS", None)
    feature_args = ["--features", ",".join(features)] if features else []
    rc = run(["cargo", "build", "--release", "--locked" if (KERNEL / "Cargo.lock").exists() else "--offline",
              "--manifest-path", KERNEL / "Cargo.toml", "--target", TARGET, *feature_args], env=env)
    if rc:
        raise SystemExit(f"FAIL: cargo exit {rc}")
    return Path(target_dir) / TARGET / "release" / "abraham-kernel", entry


def write_info(mode, extra):
    info = {
        "mode": mode,
        "rustc": version(["rustc", "-V"]),
        "cargo": version(["cargo", "-V"]),
        "nasm": version([tool("nasm"), "-v"]),
        "installed_targets": installed_targets(),
        "inputs": inputs(),
        **extra,
    }
    BUILD.mkdir(exist_ok=True)
    (BUILD / "build-info.json").write_text(json.dumps(info, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in info.items() if k != "inputs"}, indent=1))


def rust_lld():
    sysroot = subprocess.run(["rustc", "--print", "sysroot"], capture_output=True, text=True).stdout.strip()
    found = sorted(Path(sysroot).glob("lib/rustlib/*/bin/rust-lld*"))
    if not found:
        raise SystemExit("BLOCKED: rust-lld not found in the Rust sysroot")
    return found[0]


def precheck():
    """Compile and link with the kernel's own linker script and NASM object, but for the
    installed musl target. The result checks code, asm and link layout; it is not bootable."""
    entry = assemble()
    target_dir = BUILD / "precheck"
    flags = rustflags(entry).split("\x1f") + [
        f"-Clinker={rust_lld()}", "-Clinker-flavor=ld.lld", "-Clink-self-contained=no",
        "-Clink-arg=--no-dynamic-linker", "-Clink-arg=-static"]
    env = dict(os.environ, CARGO_TARGET_DIR=str(target_dir), CARGO_ENCODED_RUSTFLAGS="\x1f".join(flags))
    env.pop("RUSTFLAGS", None)
    rc = run(["cargo", "build", "--release", "--offline", "--manifest-path", KERNEL / "Cargo.toml",
              "--target", CHECK_TARGET], env=env)
    elf = target_dir / CHECK_TARGET / "release" / "abraham-kernel"
    ok = rc == 0 and elf.is_file()
    write_info("precheck", {
        "result": "PASS" if ok else "FAIL",
        "note": "compile+link check only, target x86_64-unknown-linux-musl (red zone, SSE): "
                "NOT a bootable Abraham kernel and never booted",
        "entry_o_sha256": sha256(entry),
        "check_elf_sha256": sha256(elf) if elf.is_file() else None,
    })
    return 0 if ok else 1


def crate_version():
    for line in (KERNEL / "Cargo.toml").read_text().splitlines():
        if line.startswith("version"):
            return line.split('"')[1]
    raise SystemExit("BLOCKED: no version in kernel/Cargo.toml")


def kernel():
    # Always clean: cargo does not track the NASM object passed as a link argument, so an
    # incremental build after an entry.asm change would silently relink nothing.
    shutil.rmtree(BUILD / "cargo", ignore_errors=True)
    elf, entry = kernel_build(BUILD / "cargo")
    # 0.31: versioned output name. The plain name abraham-kernel.elf is, in work-0.29, the
    # frozen 0.1.0 copy; no 0.31 build ever writes a file of that name.
    out = BUILD / f"abraham-kernel-{crate_version()}.elf"
    shutil.copyfile(elf, out)
    write_info("kernel", {"result": "PASS", "target": TARGET, "entry_o_sha256": sha256(entry),
                          "kernel_elf": out.name, "kernel_elf_sha256": sha256(out)})
    return 0


def repro():
    digests = []
    for n in (1, 2):
        target_dir = BUILD / f"repro{n}"
        shutil.rmtree(target_dir, ignore_errors=True)
        elf, _ = kernel_build(target_dir)
        digests.append(sha256(elf))
    same = digests[0] == digests[1]
    write_info("repro", {"result": "PASS" if same else "FAIL", "target": TARGET, "elf_sha256": digests})
    return 0 if same else 1


def diag(feature):
    """Diagnostic build: kernel with one cargo feature, or several joined by commas (0.31a),
    written to build/diag/ only (name joins features with '+'). Never touches the main kernel
    output or build/build-info.json."""
    if not all(f.startswith("diag-") for f in feature.split(",")):
        raise SystemExit(f"REFUSED: diagnostic builds take diag-* features only, got {feature!r}")
    name = feature.replace(",", "+")
    target_dir = BUILD / f"diag-{name}"
    shutil.rmtree(target_dir, ignore_errors=True)
    elf, entry = kernel_build(target_dir, features=(feature,))
    out_dir = BUILD / "diag"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"abraham-kernel-{name}.elf"
    shutil.copyfile(elf, out)
    info = {"mode": "diag", "feature": feature, "label": "DIAGNOSTIC build, never an accepted kernel",
            "version": crate_version(),
            "rustc": version(["rustc", "-V"]), "nasm": version([tool("nasm"), "-v"]), "inputs": inputs(),
            "entry_o_sha256": sha256(entry), "kernel_elf": str(out.relative_to(OS)), "kernel_elf_sha256": sha256(out)}
    (out_dir / f"build-info-{name}.json").write_text(json.dumps(info, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in info.items() if k != "inputs"}, indent=1))
    return 0


if __name__ == "__main__":
    modes = {"precheck": precheck, "kernel": kernel, "repro": repro}
    if len(sys.argv) == 3 and sys.argv[1] == "diag":
        raise SystemExit(diag(sys.argv[2]))
    if len(sys.argv) != 2 or sys.argv[1] not in modes:
        raise SystemExit(__doc__)
    raise SystemExit(modes[sys.argv[1]]())
