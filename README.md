```text
 __  __    ___    ____    _  __   ___
|  \/  |  / _ \  / ___|  | |/ /  / _ \
| |\/| | | | | | \___ \  | ' /  | | | |
| |  | | | |_| |  ___) | | . \  | |_| |
|_|  |_|  \___/  |____/  |_|\_\  \___/  (TM)

MOSKO(TM) - MOSKO Laboratory 001, Pripyat - Digital Front
```

# Abraham

Abraham is MOSKO's operating system: an x86-64 kernel in Rust (`no_std`) and NASM, booted by Limine under UEFI. This
repository holds the source and documentation of **revision 0.33c**:
- the 0.33.0-dev kernel, with its service manager, application registry and launcher contract;
- the Windows VM launcher 0.33.2, which boots Abraham in QEMU and shows its console with a live status panel.

**Status: 0.33c is complete and under independent audit. It is not yet accepted.** The 0.34 "First Light" document is
a design proposal only. Nothing in it is implemented.

## What is here

| Path | What |
|---|---|
| `work-0.33c/kernel/` | the kernel: `src/` (Rust), `asm/` (NASM entry), `linker.ld`, `hosttest/` (hosted tests) |
| `work-0.33c/tools/` | build (`build.py`), the boot harness and judges (`abr_boot_001.py`, `g*/`), campaign and verification tools |
| `work-0.33c/docs/` | designs, reviews, kernel diagnostics, operator checklists and the 0.33c limitations register |
| `work-0.33c/boot/` | the Limine boot-entry template |
| `vmlauncher-0.33.2/` | the Windows VM launcher: `src/` (Rust, no dependencies), `tools/` (`verify_run.py` and test tools), `docs/` |
| `ABRAHAM_0.1_BASELINE.md`, `ABRAHAM_0.2_BASELINE.md` | the ratified baselines (the C12/C13 checkers read Appendix A from the 0.2 baseline) |
| `ABRAHAM_0.33_DESIGN.md`, `ABRAHAM_0.34_FIRST_LIGHT_DESIGN_PROPOSAL.md` | the 0.33 design; the 0.34 proposal (not approved) |
| `PATCH_NOTES_*.md`, `0.33c_LIMITATIONS_ADDENDUM.md` | plain-language patch notes, and the open limitations after the operator campaign |
| `PUBLISH_MANIFEST.json` | the SHA-256 of every file here and of its source in the development tree |

The folder names are the development tree's own, so the relative paths in the tools and docs still hold.

## Not included

- **Third-party binaries and tools:**
  - QEMU 11.1.0 (Weil build 20260811);
  - edk2 UEFI firmware;
  - Limine 12.9.6 (`BOOTX64.EFI`);
  - the Rust and NASM toolchains.

  The tools expect them at pinned paths and check them by SHA-256 (`vmlauncher-0.33.2/src/pins.rs`).
- **Build output:** the kernel ELFs and the launcher program. Tested identities:
  - kernel `6b95b9a27a8eedd68dd5023dbf99e73716aa1be88780ddde406099679e119a21`;
  - launcher `d7f2fc573421134bc4325128f3f896ea79e0afd25586e3c6f5fa641622fb67e4`.
- **Test evidence, run records, decisions and audit packages.** These stay in the laboratory's records.

## Build (outline)

```
cd work-0.33c
python -I -B tools/build.py kernel        # build/abraham-kernel-0.33.0-dev.elf
cd ../vmlauncher-0.33.2
cargo build --release --offline           # target/release/Abraham-VM-Launcher.exe
```

## Rights

Copyright (c) MOSKO. All rights reserved. No license is granted. MOSKO is a trademark.
