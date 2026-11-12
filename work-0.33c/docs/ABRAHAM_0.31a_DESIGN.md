# ABRAHAM 0.31a: frame ownership and frame allocator (design for owner checkpoint)

- Date: 2026-11-05. Laboratory 001 - Pripyat. Status: **DESIGN, awaiting Jadin's review (handoff Step 3)**.
- Scope: handoff §7 Steps 2-4; Echo audit F-029-01 (page-table frame collision). Baseline: ABRAHAM 0.2 §3A
  ("establish kernel-owned execution context, memory ownership and error reporting").
- Tree: `Documents\Abraham\work-0.31` (copied from 0.29 and verified: `COPY_MANIFEST_FROM_0.29.json`).
  `frozen\` and `work-0.29\` are never written.

## 1. What the running 0.29 kernel actually does (measured, probe runs ABR-0.31a-P001 WHPX, P002 TCG)

The probe kernel (`diag-memmap`, DIAGNOSTIC only) printed the full Limine memory map and walked the live
page tables before and after the APIC mapping. Both accelerators gave the identical map: 33 entries,
218,566,656 usable bytes.

| What | Where (physical) | Map type | Notes |
|---|---|---|---|
| Limine's page tables (9 frames) | `0xe0e5000`-`0xe0ef000` | BOOTLOADER_RECLAIMABLE (entry 13) | PML4 `0xe0ef000` |
| **0.29 APIC page tables (2 frames)** | **`0xbf6b000` (PD), `0xbf6a000` (PT)** | **USABLE (entry 8)** | taken privately by `paging.rs` from the top of the largest USABLE region; the map still says "free" |
| Kernel image | `0xe103000`-`0xe11f0d0` | EXECUTABLE_AND_MODULES (entry 14) | from the Limine Executable Address request |
| Frame 0 and low memory | `0x0`-`0xa0000` | USABLE (entry 0) | base revision 3+ may report page 0 as usable |
| APIC registers | `0xfee00000` | not RAM; in no map entry | mapped uncached by `paging.rs` |

This is F-029-01 made concrete: an allocator that trusts the memory map would hand out `0xbf6a000` and
`0xbf6b000`, which are live page tables, and overwriting them would break the APIC mapping.

## 2. Design (smallest mechanism that removes the collision)

1. **One owner for usable RAM.** A new frame allocator (`kernel/src/frame.rs`) is created from the
   memory map **before any page table is built**. `paging.rs` loses its private bump allocator
   (FRAME_TOP/FRAME_FLOOR) and asks the allocator for page-table frames. Those frames are **pinned**: they
   leave the pool for good and can never be released or handed out again. A collision is then impossible
   by construction, not just avoided by a count.
2. **Two bitmaps, fixed size, no heap.** `pool` (frame came from a validated USABLE range and is not
   reserved) and `free`. 4 GiB of physical address space is managed (1,048,576 frames, 2 x 128 KiB in
   kernel .bss). USABLE memory above 4 GiB is counted as UNMANAGED and never handed out in 0.31.
3. **Ownership ledger.** Explicit reservations applied on top of the map: `LOW_1MIB` (0-1 MiB, so frame 0 is
   never returned and legacy/trampoline space stays untouched) and `KERNEL_IMAGE` (from the Executable Address
   request, defense in depth). Every other non-USABLE type stays reserved. BOOTLOADER_RECLAIMABLE stays
   reserved: **no reclaim in 0.31** (handoff Step 2).
4. **Fail-safe map validation.** Zero-length entries skipped; overflowing entries rejected; a misaligned
   USABLE entry trimmed inward to whole frames; anything non-USABLE that touches part of a frame removes the
   whole frame; overlaps resolved as "reserved wins"; duplicate USABLE counted once; unknown types reserved;
   unsorted maps handled (order-independent). Each case is counted as an anomaly and reported.
5. **Typed frames.** `alloc()` returns a `Frame` that cannot be copied or forged. `release(frame)` and
   `pin(frame)` consume it, so Rust code cannot use a frame after releasing it. Raw-address release is
   checked: misaligned, out of range, not allocator-owned (reserved, pinned, never usable) and double release
   are all refused with a code. Released frames are poisoned; newly allocated frames are zeroed.
6. **Exhaustion.** `alloc()` returns `OUT_OF_MEMORY`. Nothing is written, nothing falls back, the event is
   counted, and the next `alloc()` after a release succeeds. If the kernel cannot get a frame for a page
   table, boot stops with `ABR|FAULT` (as 0.29 did with NO_FREE_FRAME): no OPERATIONAL.
7. **Ownership check on the live kernel (STOP condition).** After the allocator starts and again after the
   APIC mapping, the kernel walks its live page tables and translates its own image. Every page-table frame
   must be in BOOTLOADER_RECLAIMABLE or be a pinned allocator frame and must never be free. No kernel-image
   frame, MMIO page or frame 0 may be in the pool, and the pool must lie wholly inside USABLE. Any violation
   prints `ABR|MEMCHECK|violation=...` and `ABR|FAULT|reason=FRAME_OWNERSHIP_COLLISION` and halts before
   OPERATIONAL.
8. **Boot diagnostics.** The default kernel prints the map, the ledger, pool counts, allocator state
   (`READY`, or `EMPTY` -> FAULT) and both checks as `ABR|MEM...` lines. The kernel version becomes
   `0.31.0-dev`, and the banner format is unchanged.

## 3. RAM ownership after 0.31a (expected on the tested VM; confirmed by the first 0.31 boot)

| Physical memory | Owner in 0.31a | Can the allocator hand it out? |
|---|---|---|
| USABLE, 1 MiB-4 GiB (about 207 MiB here) | frame allocator pool | **Yes** |
| 0-1 MiB (includes frame 0, which the map calls USABLE) | ledger `LOW_1MIB` | No |
| Page tables Abraham creates (2 frames today) | `PAGE_TABLE`, pinned | No, never again |
| BOOTLOADER_RECLAIMABLE (Limine's page tables, GDT, stack, map, responses) | Limine, kept | No (no reclaim in 0.31) |
| Kernel image | ledger `KERNEL_IMAGE` | No |
| ACPI, NVS, RESERVED, RESERVED_MAPPED, BAD, FRAMEBUFFER | firmware / hardware | No |
| APIC MMIO `0xfee00000` (not RAM) | device | No (never in the pool) |
| USABLE above 4 GiB (none on this VM) | UNMANAGED, counted | No (0.31 limit) |

**When it runs out:** `OUT_OF_MEMORY` to the caller, memory untouched, counter raised; boot-critical callers
stop the kernel with a FAULT line instead of continuing with a fake frame.

## 4. Tests (Step 5)

| Kind | Test | Label |
|---|---|---|
| Positive | host unit tests: frames aligned, unique, only from USABLE, never reserved/pinned; count exact | SIMULATED (hosted) |
| Positive | differential test: bitmap allocator vs a naive per-frame model on many generated maps | SIMULATED |
| Negative | exhaustion -> OUT_OF_MEMORY, sticky, no write; release/realloc; double release; pinned/reserved/misaligned/out-of-range release refused | SIMULATED |
| Negative | malformed maps: zero-length, overflow, misaligned, unsorted, overlapping, unknown type, empty, all reserved, above 4 GiB | SIMULATED |
| Negative | use-after-release and forged frames rejected at compile time (compile-fail test plus a compiling twin) | SIMULATED |
| Positive (VM) | 0.31 kernel on WHPX and TCG: C1-C8 unchanged plus C9 memory ownership | VM_MEASURED |
| Positive + negative (VM) | `diag-mem-exhaust`: allocate every frame to OUT_OF_MEMORY, write a pattern and tag into each, verify none is a page table or kernel frame, then release and keep heartbeats | VM_MEASURED |
| **VM negative control (F-029-01)** | `diag-legacy-collision`: 0.29 private bump plus a full-map allocator; the boot check must report the two live frames and stop with FRAME_OWNERSHIP_COLLISION | VM_MEASURED |
| VM negative control | same build with the check non-fatal plus exhaust: the allocator is shown handing out the live page-table frames (detected before writing) | VM_MEASURED |
| Regression | 0.29 kernel `ef751eaf` and frozen `5c2e7700` byte-identical; 0.31 cold restart and fresh epoch (WHPX, TCG); TCG warm reset; #UD/#PF fault reports; repro build; WHPX warm reset stays excluded | VM_MEASURED / host |
| Harness self-test | wrong kernel digest refused; missing log, false banner, removed MEMCHECK, injected violation, failed timer opt-out (F-029-05), killed QEMU: all FAIL; unchanged control PASS | host / VM_MEASURED |

A host unit test says nothing about the running kernel's memory safety; only the VM runs do (handoff Step 5).

## 5. Boundaries and risks

- Single CPU, interrupts never allocate; the allocator refuses re-entry (`ALLOCATOR_BUSY`) instead of locking.
- Raw physical addresses taken out of a `Frame` (to write a page-table entry) cannot be tracked by Rust; only
  pinned page tables do this in 0.31a.
- No heap, no unmapping, no page-table freeing, no SMP, no reclaim of BOOTLOADER_RECLAIMABLE or ACPI memory.
- 4 GiB managed limit, 256 KiB of .bss.
- Not in 0.31a (later 0.31 sub-revisions): F-029-02 diag_reset label, F-029-03 timing_probe dead code,
  F-029-04 TSC backward guard.

## 6. Owner questions

1. Approve this design for implementation in `work-0.31`?
2. **Reason codes (P-15).** The new codes (`OUT_OF_MEMORY`, `FRAME_NOT_OWNED`, `FRAME_DOUBLE_RELEASE`,
   `FRAME_MISALIGNED`, `FRAME_OUT_OF_RANGE`, `FRAME_OWNERSHIP_COLLISION`, `FRAME_ALLOCATOR_UNAVAILABLE`)
   appear only on kernel `ABR|FAULT`/`ABR|MEM` diagnostic lines, like 0.29's `NO_FREE_FRAME` and
   `TIMER_UNAVAILABLE`. Appendix A says new codes are added only there. Option A: treat them as kernel
   diagnostics outside Appendix A (no baseline change). Option B: add them to Appendix A, which is a
   ratified baseline revision and must come before implementation.
