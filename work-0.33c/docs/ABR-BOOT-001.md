# ABR-BOOT-001: first native boot of the Abraham kernel

- **Designation:** ABR-BOOT-001 (operator directive, MOSKO LABORATORY 001 - PRIPYAT, 2026-11-01)
- **Objective:** boot Abraham's native x86-64 kernel under QEMU using UEFI.
- **Architecture (ratified, ABRAHAM 0.2):** x86-64 under QEMU with UEFI (P-01); an existing
  boot protocol, here Limine, the one P-01 names; NASM for entry and trap stubs; kernel in
  Rust `no_std` (P-02); serial console as the display path (P-14); per-boot RDRAND epoch,
  DEGRADED without entropy (P-11); privilege boundary COOPERATIVE (ring 0, P-10).
- **Status on 2026-11-01:** **executed.** C1-C8 PASS on WHPX (R002, R003; C7 series PASS).
  TCG run R004 fails C5 (slow heartbeat against host time). Record: TR-0013. Not an acceptance.
  Since first written: Limine base revision 6; local APIC timer instead of PIC/PIT (Limine 5+
  masks the PIC path); kernel BLAKE2b pinned in limine.conf; C6 judged by cold restart (§5).
- **Decision 2026-11-01 (Jadin, D-ABR-001):** C6 is accepted as a harness-driven cold restart.
  This settles how C6 is judged. It does not accept ABR-BOOT-001 as a whole.
- **Decision 2026-11-01 (Jadin, D-ABR-002):** C5 is judged on WHPX runs only. TCG runs are
  informational; R004's C5 FAIL stays recorded but does not count. Counted runs: R002, R003.
- **ACCEPTED 2026-11-01 (Jadin, D-ABR-003):** ABR-BOOT-001 is complete on the tested
  configuration: kernel `5c2e7700...caa2`, Limine 12.9.6, edk2, QEMU 11.0.93, WHPX. It says
  nothing about other configurations, hardware, warm reset, or Abraham capabilities beyond
  this milestone.

A standalone EFI application does not satisfy this milestone. The kernel is a separate
ELF image, loaded by the bootloader after UEFI, running on its own GDT, TSS, IDT and
stack, with its own interrupt handling.

## 1. What the kernel does (kernel/)

| Stage | Code | Serial evidence |
|---|---|---|
| Bootloader jumps to `abr_entry` | asm/entry.asm: own 64 KiB stack, writes to COM1 before any Rust runs | `ABR\|ENTRY\|abr_entry reached (NASM)` |
| Rust entry | src/main.rs `abr_kmain` | `ABR\|STAGE\|kmain entered (Rust no_std)` |
| Handoff check | src/limine.rs: base revision, bootloader info, memory map, HHDM | `ABR\|BOOTINFO\|loader=Limine <ver>\|base_revision_supported=true` |
| Own descriptor tables | src/cpu.rs + NASM `abr_load_gdt/idt/tss`; #DF on IST1 | `ABR\|STAGE\|gdt+tss+idt loaded` |
| Boot epoch | src/entropy.rs, RDRAND only | in the banner |
| Timer | 8259 PIC remapped and left masked; local APIC timer periodic at 100 Hz on vector 32, calibrated by polling PIT channel 2; spurious vector 255; `sti` (src/apic.rs, src/paging.rs) | `ABR\|STAGE\|timer=lapic-periodic\|apic_mode=...\|apic_ticks_per_10ms=...` |
| Banner | src/main.rs | `ABRAHAM \| MOSKO native kernel 0.1.0-dev \| ABR-BOOT-001` and `ABR\|BANNER\|...` |
| Operational | after the first timer interrupt is handled | `ABR\|STATE\|OPERATIONAL` |
| Heartbeat | idle `hlt` loop | `ABR\|TICK\|uptime_s=N` each second |
| Any CPU exception | NASM stub -> `abr_trap`, reports, then halts | `ABR\|FAULT\|vector=...` (never silent) |

## 2. Acceptance conditions and how the harness judges them (tools/abr_boot_001.py)

| # | Condition (directive) | Judged PASS only if |
|---|---|---|
| C1 | UEFI loads the selected bootloader | firmware logs `BdsDxe: starting Boot#### ... from PciRoot(...)` (the boot disk, not the built-in shell) **and** the kernel reports `loader=Limine ...` with the base revision supported |
| C2 | Execution enters the Abraham kernel | the NASM entry line and the Rust `kmain` line both appear |
| C3 | Stable operational state | `ABR\|STATE\|OPERATIONAL` (printed only after a real timer interrupt) and ticks |
| C4 | Recognizable banner | both banner lines, matched exactly |
| C5 | No crash or triple fault (judged on WHPX runs only; TCG is informational, D-ABR-002) | no `ABR\|FAULT`, no guest-initiated QMP `RESET` event, ticks consecutive for the stability window (default 15 s, at least window - 2 ticks), QMP `query-status` = running |
| C6 | Clean restart through the harness (cold restart accepted by Jadin 2026-11-01, D-ABR-001) | default `--restart cold`: boot 1 ends by QMP quit (SHUTDOWN host-qmp-quit, exit 0) with no RESET in either process; the same boot disk and NV variable store are relaunched; boot 2 shows the NASM entry, a banner, OPERATIONAL, at least 2 ticks, and a `boot_epoch` different from boot 1. `--restart warm` (QMP `system_reset`) is kept but does not work on this platform (§5) |
| C7 | Reproducible | `series`: at least 2 PASS runs with identical kernel and loader digests, and `build.py repro` gives two byte-identical ELFs |
| C8 | Complete build and QEMU evidence | serial.log, qmp.jsonl, host.json (command, versions, input digests, timeline, build-info), results, staged boot disk; sealed in RUN_SHA256SUMS.json and re-hashed |

Every run is VM_MEASURED (P-48). PASS is a measurement, not an acceptance.

## 3. Steps once the blockers are cleared

1. `rustup target add x86_64-unknown-none`
2. Obtain the Limine binary release chosen by the operator; record its URL, version and
   SHA-256 in the run record; keep the archive.
3. **Before building, check against that exact release:**
   - every request ID and the base revision in `kernel/src/limine.rs` against its `limine.h`;
   - the option names in `boot/limine.conf` against its `CONFIG.md`.
   Any change is made and recorded before R001.
4. Build:
   ```
   python tools/build.py precheck
   python tools/build.py kernel
   python tools/build.py repro
   ```
5. Boot (WHPX twice, TCG once; run ids never reused):
   ```
   python tools/abr_boot_001.py run --run-id ABR-BOOT-001-R001 --accel whpx --limine-efi <path>\BOOTX64.EFI
   python tools/abr_boot_001.py run --run-id ABR-BOOT-001-R002 --accel whpx --limine-efi <path>\BOOTX64.EFI
   python tools/abr_boot_001.py run --run-id ABR-BOOT-001-R003 --accel tcg  --limine-efi <path>\BOOTX64.EFI
   python tools/abr_boot_001.py series ABR-BOOT-001-R001 ABR-BOOT-001-R002 ABR-BOOT-001-R003
   ```
6. Optional negative control for P-11: `--cpu qemu64` (no RDRAND). Expected banner
   `status=DEGRADED|reason=ENTROPY_UNAVAILABLE`; C6's epoch-freshness part becomes not
   applicable.

Under the hood each run is (from host.json):
```
qemu-system-x86_64 -machine q35 -accel whpx -cpu host -smp 1 -m 256 -display none -nodefaults -nic none
  -serial file:<run>\serial.log -qmp tcp:127.0.0.1:<port>,server=on,wait=off
  -drive if=pflash,format=raw,readonly=on,file=C:\Program Files\qemu\share\edk2-x86_64-code.fd
  -drive if=pflash,format=raw,file=<run>\vars.fd
  -drive file=fat:ro:<run>\esp,format=raw,if=virtio,readonly=on
```
with `<run>\esp` = `EFI\BOOT\BOOTX64.EFI` (Limine), `boot\limine\limine.conf`, `boot\abraham-kernel`.

## 4. Blockers (2026-11-01, cleared the same day)

Both downloads were approved by Jadin and are recorded in TR-0013.

| Blocker | Why | Needs |
|---|---|---|
| Rust target `x86_64-unknown-none` not installed | The kernel's ratified form is Rust `no_std` for bare x86-64: no red zone, no SSE in kernel code, `rust-lld`. The installed targets are Windows and Linux-musl; a musl build is only a compile check (red zone and SSE make it unsound for interrupts on the kernel stack) and is never booted. | Operator approval to download it from static.rust-lang.org via rustup |
| No bootloader binary | P-01 chose an existing boot protocol; no C compiler here to build Limine from source. | Operator approval for the Limine binary release, or a decision to write a MOSKO UEFI loader instead (also needs a download: `x86_64-unknown-uefi`) |

Not blockers, already measured on 2026-11-01:
- UEFI firmware runs under QEMU 11.0.93 on WHPX and TCG, sees the virtual FAT boot disk
  and tries it first (harness self-tests HARNESS-0001, HARNESS-0002).
- NASM 3.02 assembles entry.asm with warnings as errors.
- The kernel compiles and links with its own linker script and NASM object
  (`build.py precheck`, compile/link check only).

## 5. Platform finding: warm reset (2026-11-01, DIAG-RESET-0001..0010)

QEMU 11.0.93 (pre-release) with its bundled edk2 cannot warm-reset this machine usefully.
- **WHPX:** after QMP `system_reset` the firmware asserts in `MemDetect.c(1181)`, because
  the MTRRs are still enabled.
- **TCG:** the firmware and loader come back, but serial output is lost and the loader stalls.

No Abraham code is involved in either. Hence the cold-restart C6. Re-test warm reset after
pinning a stable QEMU release.
