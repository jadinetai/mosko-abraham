# Patch notes: ABRAHAM 0.31a (kernel 0.31.0-dev)

For Jadin. 2026-11-05, MOSKO Laboratory 001 - Pripyat. Record TR-0033.
**Status: 0.31a READY FOR AUDIT. Not accepted. 0.31 IN PROGRESS. Nothing advances to 0.32 without your decision.**

## In one paragraph

Echo's audit found that the 0.29 kernel quietly took two pages of "free" memory for page tables without telling
anyone (F-029-01). Any future allocator that believed the memory map would have handed those live pages out and
corrupted the kernel. 0.31a gives Abraham a single owner for physical memory. The frame allocator starts before any
page table exists, every page table it supplies is pinned for good, and the running kernel proves twice per boot,
before it calls itself operational, that no live page is in the free pool. A double release or an ownership collision
is no longer something to note and move past: the allocator locks itself and the kernel stops (your D-ABR-012).

## Direct changes

| File | What changed | Why |
|---|---|---|
| `kernel/src/frame.rs` (new, 715 lines) | The frame allocator: two bitmaps (pool, free) over 4 GiB, held in .bss (no heap, no `unsafe`). It validates the memory map defensively, applies a reservation ledger, hands out frames that cannot be copied or forged, pins page tables, returns `OUT_OF_MEMORY` when empty, and **latches FAULTED** on a double release or a collision | F-029-01; your design approval (D-ABR-009); D-ABR-012 |
| `kernel/src/memory.rs` (new) | The one allocator instance; reservations for 0-1 MiB, the kernel image and the APIC page; a guard that refuses any live frame at allocation time; the stop path for serious violations; the live ownership check | Same |
| `kernel/src/ptwalk.rs` (new) | Reads the real page tables (never writes) so the kernel can prove ownership on itself | "Demonstrate non-overlap" (audit) |
| `kernel/src/paging.rs` | **Private bump allocator removed.** APIC page tables now come from the allocator, zeroed and pinned. The old 0.29 code is kept only inside a negative-control build | The fix itself |
| `kernel/src/main.rs` | New order: loader checks, allocator, ownership check, descriptor tables, timer, ownership check, banner, OPERATIONAL | No allocation can happen before the owner exists |
| `kernel/src/limine.rs`, `kernel/linker.ld` | The kernel asks Limine where it was placed (the map entry for it is "illustrative only") and knows its own size | Reserve the kernel image exactly |
| `kernel/src/memtest.rs`, `memprobe.rs` (new) | Test-only builds: exhaust all memory on the live kernel; print the map for the design review | Evidence |
| `kernel/hosttest/` (new) | The kernel's own `frame.rs` compiled on Windows for unit tests (MSVC 14.51 turned out to be installed) | Deterministic host tests (P-08) |
| `tools/abr_boot_001.py` | The harness now **refuses a kernel whose SHA-256 is not the one you name**; requires `--profile`; new C0 (the Windows timer opt-out must have worked, Echo F-029-05); new C9 (memory ownership) | Handoff Step 5 harness self-tests |
| `tools/g6/fault_probe.py` | Digest pin; three new expected-failure judgments | Negative controls |
| `tools/build.py` | Output is `abraham-kernel-0.31.0-dev.elf` (never the plain name, which in `work-0.29` is the frozen 0.1.0 copy) | Avoid confusion and accidental overwrite |
| `tools/g031/*` (new) | Branch copy, inventory, host tests, code-registry check, judge self-test, campaign driver, source diff | Reproducible, recorded testing |
| `docs/KERNEL_DIAGNOSTICS.md` (new) | Registry of all 124 kernel codes, with severity; a checker fails if the kernel prints an unregistered one | Your instruction (D-ABR-012) |
| `..\DECISIONS.md` | D-ABR-009..012 appended (rows only) | Your four decisions today |

Unchanged on purpose: `entry.asm` (byte-identical), the banner format, the boot protocol, `frozen\`, `work-0.29\`
(0 files written there today, verified).

## Evidence (all in `work-0.31\evidence`, every run sealed)

- **31 recorded test runs, 31 behaved exactly as written down before they ran** (`evidence/campaign-031a/campaign.json`).
- Normal boots (W001, W002 WHPX; T001, T002 TCG; R001, R002 TCG warm reset): PASS. Each of the 12 boots shows the
  same result: 53,133 frames owned, 0 map anomalies, 9 Limine tables in bootloader memory, 2 Abraham tables pinned
  at `0x100000` and `0x101000`, 0 violations, then OPERATIONAL and heartbeats.
- Exhaustion on the live kernel (E001 WHPX, E002 TCG): all **53,129** free frames (207.5 MiB) taken, each checked
  before anything was written, filled and re-read intact; `OUT_OF_MEMORY` and it stays that way; 16 illegal releases
  refused (all 11 live page tables among them); everything released; the kernel then runs normally.
- **The audit's hazard, reproduced and caught** (N001 WHPX, N002 TCG): with the 0.29 bump allocator put back, the
  check finds `0xbf6b000` and `0xbf6a000` (the very frames measured on the 0.29 kernel) sitting in the free pool,
  and stops the boot before OPERATIONAL.
- **D-ABR-012 collision** (N003, N004): even with that check muted, the allocator refuses to hand out `0xbf6a000`,
  quarantines it, locks itself and stops the kernel. The APIC mapping is still intact, so the page was never touched.
- **D-ABR-012 double release** (N005, N006): releasing `0x103000` a second time leaves the free pool at exactly 53,130
  (counter equals bitmap), locks the allocator and stops the kernel.
- Host tests (H001): 36/36, including a 3,000-map random comparison against an independently written model, and 6
  compile-time ownership checks verified for the exact compiler error.
- Regression: the accepted 0.29 kernel still passes under the new harness (G001); #UD, #PF and early-failure reports
  are unchanged (F001-F005); two clean builds are byte-identical (B001); the freeze and the 0.29 sign-off are untouched (I002).
- Harness self-test (J001): 37 falsified copies of a good run all FAIL, the untouched copy PASSes.

## Failures, and why

### Runs that were supposed to fail, and did

| Run | What failed | Why that is correct |
|---|---|---|
| N001-N006 | the kernel stopped with a FAULT | each is a deliberately broken DIAGNOSTIC build; the test passes when the right stop is observed with the right numbers |
| N007 | C9 | the 0.29 kernel has no memory-ownership report; this proves C9 checks something real. It passed C0-C8 |
| N008 | refused, exit 2 | a wrong kernel digest was given on purpose; nothing ran, no folder was created |
| N009 | C0, C3, C5, C6, C8, C9 | QEMU was killed mid-run on purpose. C0 fails too because the second QEMU process never started, so there is no opt-out evidence for it, and the judge does not assume it |
| N010 | kernel refused by Limine | a one-byte-tampered kernel; the loader's hash check held |
| K002 | checker FAIL | a fake unregistered code was planted in a scratch copy; the registry check caught it |
| J001 | 37 of 38 cases FAIL | each case is a falsified copy of good evidence; all 37 were rejected |

### My own mistakes, found and fixed before the recorded campaign

1. **Handoff missing at the start.** Only the audit was attached. I stopped before any source change and asked;
   you added the file.
2. **Allocator reuse rule (a real bug, caught before any test run).** The "next fit" search remembered a 64-frame
   word, not a frame, so a frame released inside that word could be handed straight back. The code comment promised
   otherwise. I found it while working out the expected result of test H06, and made the search frame-exact.
3. **Host test H16 failed once.** My test map listed two entries in descending order; the allocator correctly
   reported an extra `UNSORTED` anomaly. The test was wrong, not the allocator; fixed the fixture.
4. **Dropped one test idea.** Checking "the allocator struct is all zero bytes" would read struct padding, which is
   undefined behavior in Rust. Replaced by measuring the real kernel ELF: the bitmaps sit in .bss (349,776 bytes),
   `.data` holds only 144 bytes, and the file is 48 KB.
5. **First kernel build refused** by Cargo: the lock file still said version 0.1.1-dev and the build runs `--locked`
   on purpose. Updated the lock file's version line (no dependencies exist).
6. **Test order would have hidden a result.** In the collision control the old page tables are marked free, so the
   planned "refuse to release a page table" step would have stopped the kernel as a double release before the
   allocation guard could be shown. I moved that step after exhaustion.
7. **Source diff tool.** `git diff --no-index` included a compiled Python cache file and skipped the new `hosttest`
   folder. Replaced by a small recorded script (`tools/g031/source_diff.py`).
8. **Checklist digests.** My first draft of the operator checklist had three diagnostic-kernel digests shifted by one
   row. They would only have been refused, but I corrected them and checked every row against the build manifest by script.
9. **Empty file inside the audit zip (after the campaign).** I sent the packaging tool's console into the very folder it
   was packaging, so the zip holds `make_audit.console.txt` as an empty file (the real one, 229 bytes, is on disk). The
   zip still verifies; the package tool refuses to overwrite, so I recorded this in TR-0033 instead of rebuilding.

### Not failures, but worth knowing

- DIAGNOSTIC builds print dead-code warnings for the paths they switch off; the real 0.31a kernel builds with none.
- Two development runs (D001, an early build; P001/P002, the design probe) are recorded but not counted as 0.31a evidence.
- `tools/g031/source_diff.py` and the review documents were written after the campaign closed; they are review
  tools, not code under test.

## Limits (what 0.31a does not claim)

4 GiB managed; no heap; no reclaim of bootloader memory; single CPU; the default kernel never releases a frame (only
the test builds do); raw addresses written into page tables are outside Rust's tracking; tested on QEMU 11.1.0 only,
not hardware. No ring 3, no security boundary beyond what was already in 0.29 (COOPERATIVE).

## Still to do in 0.31

- **0.31b must verify double release and collision again** (D-ABR-012).
- F-029-02 (diag_reset label), F-029-03 (timing_probe dead code), F-029-04 (TSC going backwards / huge uptime).
- Initialization state, minimal events, fault diagnostics (handoff §5).

## Next single step

Your review (and Echo's, using `evidence/review/ABRAHAM_0.31a_ECHO_AUDIT.zip`), then your decision on 0.31a.
