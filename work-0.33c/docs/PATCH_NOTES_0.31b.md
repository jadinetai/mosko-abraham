# Patch notes: ABRAHAM 0.31b (kernel 0.31.1-dev)

For Jadin. 2026-11-05, MOSKO Laboratory 001 - Pripyat. Record TR-0034.
**Status: 0.31b READY FOR AUDIT. Not accepted. Nothing advances to 0.32 without your decision.**

## In one paragraph

Echo showed that the 0.31a test judge could be fooled: by a run made without the Windows timer fix, by a failed
memory-check line hidden in front of a passing one, and by pin records deleted or falsified. Echo also found a
subtraction in the kernel's own memory check that could wrap around on an unusual memory map.

0.31b closes all four. The judge now refuses every falsification I could build, 38 of 38, where the old judge was
fooled by 31. The memory check counts without subtracting. Three leftovers from 0.29 are closed: a wrong label in a
diagnostic tool, dead code in the timing tool, and a clock that could jump backwards into a huge uptime.

It also completes the rest of 0.31:
- a boot lifecycle that can only move forward;
- a fixed 32-record diagnostic event log (your ABR-031-EVT-01), with no memory allocation and no dispatch;
- fault reports that say where in the boot they happened, show what happened just before, and never invent a time.

The double-release and collision tests you required (D-ABR-012) were run again on the final kernels, on both
accelerators.

## Direct changes

| File | What changed | Why |
|---|---|---|
| `tools/abr_boot_001.py` | C0 checks the timer fix was really applied to every QEMU process; a run without it is labelled CONTROL_NOT_QUALIFYING and can never PASS. C9 reads memory-check lines strictly (exactly once each, in order, before OPERATIONAL) and checks every pin record. New profile 0.31b adds C10 (lifecycle and event log) and C11 (clock) | Echo F-031a-E01, E02, E03 |
| `kernel/src/frame.rs` | New `pool_frames_outside`: counts frames outside USABLE memory directly, so overlaps can't double-count. Counter updates are checked and refuse instead of wrapping | Echo F-031a-E04 |
| `kernel/src/memory.rs` | Uses the new count; records memory events; reports through the new fault path; a diagnostic build can inject a duplicate map entry | E04, events, faults |
| `kernel/src/clockguard.rs` (new), `clock.rs` | Uptime now advances only by forward steps between readings. A backward step adds nothing; a jump of more than 5 s is kept but reported; after either, the clock is marked DEGRADED for the rest of the boot and every heartbeat shows the anomaly count | F-029-04, without a false "time is fine" claim |
| `kernel/src/lifecycle.rs` (new), `init.rs` | Eight boot states, forward one step at a time; any skip, step back or repeat stops the kernel. OPERATIONAL is only reachable after both memory checks pass | 0.31 initialization state |
| `kernel/src/events.rs` (new), `eventlog.rs` | 32-record log in fixed kernel storage: lifecycle steps, memory checks, timer start, clock anomalies, faults. When full the oldest is replaced and counted. Printed at OPERATIONAL | ABR-031-EVT-01, D-ABR-015/016 |
| `kernel/src/fault.rs` (new), `kcell.rs` (new), `cpu.rs` | Every stop goes through one path that prints the boot state, the uptime (or NONE before the clock starts), a FAILED transition and the last events, and refuses to fault again while reporting | 0.31 fault diagnostics |
| `kernel/src/main.rs` | Lifecycle steps at each stage; guarded heartbeat with a bounded catch-up; event log printout; new diagnostic hooks | Wiring |
| `tools/diag_reset.py` | Label says what was actually staged; with Abraham staged it requires a kernel and its digest | F-029-02 |
| `tools/g4/timing_probe.py` | Dead `window ... or True` removed; the real measurement window is applied and reported next to the old numbers | F-029-03 |
| `tools/g6/fault_probe.py` | Also checks the new fault report (state, FAILED, context); new lifecycle-skip test | Test the implementation |
| `tools/g031b/*` (new) | Verification, the copy, reproducing Echo's findings against both judges, re-judging old runs, observation probe, static checks, self-tests, campaign | Evidence |
| `docs/KERNEL_DIAGNOSTICS.md` | 28 new codes (152 total); the checker now also catches tags written as strings | D-ABR-012 registry |
| `..\DECISIONS.md` | D-ABR-013..016 appended (rows only) | Your decisions and requirement today |

Unchanged on purpose: `paging.rs`, `entry.asm`, the banner, the boot protocol. `frozen\`, `work-0.29\` and
`work-0.31\` are untouched; 991 of 991 files were re-verified at the end (V003).

## Evidence (all in `work-0.31b\evidence`, every run sealed)

- **52 recorded campaign entries, 52 behaved exactly as written down before they ran**, including 9 post-checks
  that read the evidence itself (`evidence/campaign-031b/campaign.json`). No source file changed during the campaign.
- **Echo's findings, before and after.** The same 38 falsified copies of a good 0.31a run:
  - the old judge was fooled 31 times (X003);
  - the new judge 0 times (X004).
  - All 12 genuinely passing 0.31a runs still pass under the new judge, and the 2 that failed by design still fail (Q001).
- **Normal boots** (WHPX and TCG, cold restart and TCG warm reset; 12 boots in all):
  - all pass C0-C11;
  - 7 lifecycle steps in order;
  - 11 events, none dropped;
  - every heartbeat shows `clock_anomalies=0`.
- **D-ABR-012 repeated** on the final builds, on both accelerators:
  - the old private page-table allocator, put back, is caught (`0xbf6b000`/`0xbf6a000`) and stops the boot (N001/N002);
  - with that check muted, the allocator itself refuses to hand out `0xbf6a000` (N003/N004);
  - a second release of `0x103000` leaves the free pool exactly as it was and stops the kernel (N005/N006).
- **Clock:**
  - TSC 2 s backwards: one report, uptime holds, heartbeats 1..12 with no repeat (O001/O002).
  - TSC 1 h ahead: one jump report and one gap line (3,599 seconds skipped) instead of 3,600 lines; heartbeats resume
    at 3603 (O003/O004).
- **E04 on the live kernel:** a duplicate memory-map entry is reported, both checks still pass, and no wrapped number
  appears anywhere (O005/O006).
- **Faults** now say where they happened:
  - #UD in OWNERSHIP_VERIFIED;
  - #PF in OPERATIONAL;
  - early failure in CPU_TABLES_LOADED with uptime NONE;
  - a lifecycle skip refused with uptime NONE.
- **Host:**
  - 73 Rust tests, including the 30 unchanged 0.31a ones and a 3,000-map property test of the new count;
  - 8 tool tests;
  - registry 152 = 152;
  - static checks: no private allocator, no allocator code linked at all, no dispatch.
- **Regression:** the 0.29 kernel and the 0.31a kernel still pass under the new harness (G001, G002). The 0.31a
  kernel fails 0.31b's new checks on exactly C10 and C11 (G003), which shows they test something real.

## Failures, and why

### Runs that were supposed to fail, and did

| Run | What failed | Why that is correct |
|---|---|---|
| X003 | the old judge got 31 of 38 cases wrong | that is Echo's finding, reproduced on purpose; the fix is X004 |
| N001-N008 | the kernel stopped with a FAULT | deliberately broken DIAGNOSTIC builds; the test passes when the right stop is seen with the right numbers |
| F001-F005 | faults | deliberate #UD, #PF and early failure; checked for state, context and halt |
| O001-O004 | clock anomalies | deliberate injected TSC steps; checked for one report and no flood |
| N009 | refused, exit 2 | wrong kernel digest on purpose |
| N010 | FAIL | QEMU killed on purpose mid-run |
| N011 | CONTROL_NOT_QUALIFYING | run without the timer fix on purpose; it must never count as PASS |
| N012 | refused by Limine | one-byte-tampered kernel |
| G003 | FAIL on C10, C11 | the older kernel has no lifecycle or clock fields |
| K002 | checker FAIL | a fake code planted in a scratch copy |

### My own mistakes, found and fixed (none reached the recorded campaign)

1. **Verifier bug (V001, kept).** My Step 1 checker looked for `D-ABR-09` instead of `D-ABR-009`, so it reported the
   decisions missing. They were present. Fixed and re-run as V002.
2. **A command that never ran.** My first attempt at the X001 reproduction wrote its console into a folder that did not
   exist yet. PowerShell stopped before Python started, nothing was produced, and I re-ran it after creating the folder.
3. **Test typo.** A test seed `0x..dbl0..` was not valid hex, so the file did not compile. Fixed.
4. **Wrong test expectation (B07).** I expected one anomaly. Appending the duplicate entry after the last one also
   makes the map unsorted, and the allocator correctly reported both. The test was wrong; fixed.
5. **Weak property test (C09).** My first version used a convoluted backward-step formula and only checked "at most
   N anomalies". Rewritten to an exact count.
6. **C10 count.** The exhaustion builds run four memory checks, not two; I caught this before any run.
7. **Design text erratum.** The approved design says "exactly the 8 transitions". There are 8 states, so a clean boot
   makes **7** transitions, which is what is implemented and tested. The document is left as approved; the erratum is
   in `0.31b_REVIEW.md` and TR-0034.
8. **Registry checker blind spot.** It missed tags written as a string on their own (`"ABR|EVENT"`). Fixed; the
   registry now has 152 codes.
9. **Line order.** The DEGRADED line would have printed before the anomaly that caused it; reordered before the first build.
10. **No-opt-out control moved to WHPX before the campaign.** On TCG, Windows throttling could have made it fail for
    an unrelated reason and hidden what it shows.
11. **A count I misstated in conversation.** I said "13 runs" stayed PASS after re-judging; the evidence says 12.
    The review uses 12.
12. **Carried from 0.31a (found in Step 1).** I had edited the 0.31a patch notes after indexing them (item 9 there).
    The indexed text is the one in Echo's zip; TR-0034 records it.

## Limits (what 0.31b does not claim)

QEMU 11.1.0 only (q35, 256 MiB, 1 vCPU), not hardware. No ring 3, no heap, no scheduler, no Secure Boot, single
CPU. The event log holds 32 records; the guard knows 64 live page tables. Static checks are text and byte scans, not
proofs. WHPX warm reset is still excluded; guest reboot is not implemented; baseline tests T01-T25 come later.

## Next

- Your review, and Echo's of `evidence/review/ABRAHAM_0.31b_ECHO_AUDIT.zip`, then your decision on 0.31b.
- The 0.32 service architecture is sketched (not built) in `docs/ABRAHAM_0.32_INTERFACE_SKETCH.md`, for your later review.
