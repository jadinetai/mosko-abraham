# ABRAHAM 0.31b design (directive Step 2, for owner approval before coding)

- 2026-11-05. MOSKO Laboratory 001 - Pripyat. Tree `Documents\Abraham\work-0.31b` (copy of reviewed 0.31a, verified).
- Inputs: `MOSKO_ABRAHAM_031A_ECHO_AUDIT_2026-11-05.md`, `MOSKO_ABRAHAM_031B_DEVELOPMENT_DIRECTIVE_2026-11-05.md`,
  D-ABR-009..013. Status: **DESIGN, nothing implemented** (only investigation tests X001, X002 exist).
- Scope limit (directive Mission): no heap, scheduler, ring 3, launcher, browser, network stack or Cyberforteca work.
  Kernel codes stay kernel diagnostics, separate from Appendix A (D-ABR-010/011).

## 0. What Step 1 and the investigation found

| Item | Finding | Evidence |
|---|---|---|
| 0.31a starting state | Verified: index `16f02153` (143 entries), 29 seals / **402 of 402** members on disk (including the 104 Echo could not re-hash from the compact zip), 9 kernels, source unchanged since the campaign (3 known post-close tools), zip `32ffc291`, TR-0033, D-ABR-009..013 | V002 (V001: my verifier's zero-padding bug, kept) |
| Documentation mismatch | `work-0.31\docs\PATCH_NOTES_0.31a.md` differs from the index and the zip: I added item 9 after indexing. The indexed text is the one in Echo's zip. Not code; to be corrected by reference in TR-0034, the file stays as is | V002 `index.entries` |
| F-031a-E01 | **Confirmed.** 2 timer cases wrongly PASS under the 0.31a judge | X001 |
| F-031a-E02 | **Confirmed and wider.** 8 summary cases wrongly PASS (hidden FAIL before PASS, duplicate, after OPERATIONAL, out of order, malformed, unknown stage, boot 2) | X001 |
| F-031a-E03 | **Confirmed and wider.** 7 MEMPIN cases wrongly PASS (all removed, in-pool/free, duplicate, extra, wrong owner, boot 2) | X001 |
| F-031a-E04 | **Confirmed.** Overlapping USABLE entries: the 0.31a sum is 8 against a pool of 6, so `6 - 8` underflows. The release build wraps to `0xfffffffffffffffe` and halts with a misleading FRAME_OWNERSHIP_COLLISION. Fails closed, but with the wrong diagnosis. Allocator ownership itself is correct (flags USABLE_DUPLICATE) | X002 (3 hosted tests on the real frame.rs) |

## 1. Judge corrections (directive Step 3) - reuse `tools/abr_boot_001.py`, stricter rules

**C0, timed configuration (F-031a-E01), every profile:**
- PASS only if the opt-out flag is exactly `true`, and for each QEMU process (boot 1, and boot 2 on a cold
  restart) the opt-out record exists with `ok=true`, `control_mask=4`, `state_mask=0`; the command contains `-S`;
  and the timeline shows `cont` sent after the opt-out.
- A run made with `--no-timer-opt-out` gets verdict **`CONTROL_NOT_QUALIFYING`** (exit 3). That verdict is never PASS.

**C9 MEMCHECK summaries (F-031a-E02):**
- Exact grammar for summary and violation lines. Any other `ABR|MEMCHECK|` line is malformed and FAILs.
- Per boot, each required stage (`init`, `timer`; plus `after_exhaust`, `after_release` for memtest builds)
  appears **exactly once**, in that order, before OPERATIONAL. Unknown stages FAIL. Any MEMCHECK line after
  OPERATIONAL FAILs.
- Consistency: `PASS` if and only if `violations=0`; `pt_tables = pt_in_bootloader + pt_pinned`; `pinned = pt_pinned`.

**C9 MEMPIN records (F-031a-E03):**
- Exact grammar.
- For stage S, the MEMPIN lines must sit between the previous summary and S's summary.
- Count = that summary's `pinned`. Frames are distinct, page-aligned and non-zero, with
  `owner=PAGE_TABLE|in_pool=false|free=false`.
- Stage `init` has none. Stage `timer` count = `page_table_frames_taken`. Later stages list the same set as `timer`.
- The kernel's own live check remains the real protection; this only makes the log judgment exact.

**Proof required (directive Step 3):**
- All 19 X001 cases and the new consistency, timing and C0 cases are run against both judges. Every falsified case
  must be PASS under the 0.31a judge where X001 showed it, and FAIL under 0.31b.
- Every sealed 0.31a PASS run is re-judged by the 0.31b judge under profile `0.31a` and must stay PASS.
- The 38 J001 cases are kept and extended.

## 2. Memory (directive Step 4)

**F-031a-E04:**
- `frame.rs` gains `pool_frames_outside(usable ranges)`. It walks the pool bits once and counts frames inside no
  given range: no sum, no subtraction, overlaps counted once.
- `memory::check` uses it (`POOL_OUTSIDE_USABLE` = that count).
- The four allocator counter decrements become checked; an impossible underflow returns
  `FRAME_STATE_INCONSISTENT` with no state change. Every other subtraction was audited safe by construction.

**Tests for E04:**
- Hosted: overlapping, duplicate, unsorted and misaligned USABLE maps give 0 outside, with no panic. Omitting a
  range is detected exactly. A 3,000-map property test checks that the count is 0 for every valid map. A counter
  forced inconsistent in a `cfg(test)` unit test is refused safely.
- VM: diagnostic `diag-map-overlap` injects a duplicate of the largest USABLE entry into what both the allocator and
  the check read. Expected: anomaly `USABLE_DUPLICATE`, **no** `POOL_OUTSIDE_USABLE`, no huge value, ownership
  intact, OPERATIONAL reached. C9 still FAILs that run, because it requires 0 anomalies.

**D-ABR-012, repeated:**
- Collision (check and guard) and double release, on the final 0.31b diagnostic builds, on WHPX **and** TCG.
- Plus the hosted H09-H12, so the results come from this revision, not reused from 0.31a.

**One-owner rule:** the production build contains no private allocator. A build check scans the default build's
features and source for the legacy path: `diag-legacy-collision` only.

## 3. F-029 carry-overs (tools and clock)

**F-029-02, `diag_reset.py` label:**
- The label derives from what was staged: `DIAGNOSTIC (firmware only, no Abraham code)` or
  `DIAGNOSTIC (Abraham staged: Limine + kernel <sha256>)`.
- `--abraham` requires `--kernel` and `--expect-kernel-sha256`.
- Tests: a hosted unit test of the label function, and two TCG runs (firmware-only; Abraham staged, expecting two
  OPERATIONAL).
- Sealed DIAG-RESET-0110 is not touched. TR-0034 records the correction reference.

**F-029-03, `timing_probe.py`:**
- Remove the dead `window ... or True`. Apply the intended window: ticks whose host time is inside
  [measurement start, measurement end].
- Report both all-ticks and in-window results.
- Tests: hosted unit tests on synthetic ticks (before/after excluded, boundaries included; and the old expression
  shown to select everything), plus one TCG probe run.

**F-029-04, TSC guard (new portable `clockguard.rs`, hosted-tested like `frame.rs`):**
- Uptime advances only by the forward difference between consecutive TSC readings; it never comes from
  `wrapping_sub` against the start value.
- **Backward reading:** adds 0, so uptime holds and never wraps. Raises anomaly `TSC_BACKWARD`.
- **Forward jump** (> 5 s between consecutive readings, which normally come every 10 ms):
  - The jump is kept in uptime and raises anomaly `TSC_FORWARD_JUMP`. Reason: under P-39, expiry runs on this
    clock, so a too-fast clock only makes grants expire early (fail-closed). Dropping the jump would make them
    live too long.
  - The heartbeat catch-up is bounded: after a gap of more than 5 s, one `ABR|CLOCK|anomaly=HEARTBEAT_GAP|...`
    line replaces the flood.
- **No false claim:** every heartbeat gains `clock_anomalies=N`. On the first anomaly the kernel prints
  `ABR|CLOCK|state=DEGRADED|reason=...` and stays DEGRADED for the rest of the boot. Uptime is then explicitly not
  claimed trustworthy.
- Tests: hosted (normal progression, backward, jump, wrap near 2^64, saturation, zero rate); diagnostic builds
  `diag-tsc-backward` and `diag-tsc-jump` on WHPX and TCG, judged by a new clock probe (one anomaly line, no
  wrap, no flood, DEGRADED kept, no fault, heartbeat continues).

## 4. Initialization lifecycle (new contract, portable `lifecycle.rs`)

`EARLY -> LOADER_VERIFIED -> MEMORY_OWNED -> MEMORY_VERIFIED -> CPU_TABLES_LOADED -> TIMER_RUNNING ->
OWNERSHIP_VERIFIED -> OPERATIONAL`, plus terminal `FAILED`.

- Each step may only go to the next one. `FAILED` is reachable from any state except itself; nothing leaves `FAILED`.
- Skipping, going back, repeating, or leaving `FAILED` is refused: `ABR|FAULT|reason=INIT_INVALID_TRANSITION`, halt.
- Each transition prints `ABR|INIT|seq=n|from=X|to=Y`. The existing `ABR|STAGE`/`ABR|STATE|OPERATIONAL` lines stay
  for compatibility. OPERATIONAL can only be entered through the lifecycle.
- Tests: hosted (the full 9x9 transition matrix, terminal FAILED); VM diagnostic `diag-init-skip` (skip to
  OPERATIONAL after MEMORY_OWNED, expect refusal and halt).

## 5. Minimal events (new contract, portable `events.rs`) - proposed interpretation

- A bounded **event log**: a ring of 32 records `{seq, uptime_ms or NONE, kind, code, arg}`. No heap.
- When full, the oldest record is overwritten and counted (`dropped`). Nothing is lost silently.
- Recorded: every lifecycle transition, every MEMCHECK result, clock anomalies, faults.
- At OPERATIONAL the kernel prints `ABR|EVENTS|recorded=n|dropped=0|capacity=32` and each record as `ABR|EVENT|...`.
- **No subscribers, no dispatch, no handlers, no queue processing:** that would need a scheduler (0.32+).
- Trap-time recording during a record in progress is skipped and counted (`lost_reentrant`), never corrupts.
- Tests: hosted (seq strictly increasing, overwrite with an exact dropped count, order, re-entry); C10 in the VM.

## 6. Fault diagnostics (extend existing paths)

- Every `ABR|FAULT` line (exceptions and kernel-detected) gains `init_state=<state>` and `uptime_ms=<n|NONE>`.
  NONE is used before the clock starts, never a fake 0.
- After it come up to 8 `ABR|FAULTCTX|...` lines (the last events) and `ABR|FAULT_END|events_dumped=n`. The
  lifecycle moves to FAILED.
- Tests: the 0.31a fault probes (#UD, #PF, early failure, collision, double release) extended to require the right
  `init_state` and a context dump whose last event matches.

## 7. Harness profile 0.31b

C0 (strict), C1-C8, C9 (strict), plus:
- **C10 lifecycle and events:** exactly the 8 transitions, in order, before OPERATIONAL; no FAILED or refusal;
  events seq 1..n, no gaps, `dropped=0`, consistent with the INIT lines.
- **C11 clock:** every heartbeat has `clock_anomalies=0`; no `ABR|CLOCK` line.

Each new condition gets falsifications in the judge self-test.

## 8. Test plan summary (directive Step 5)

| Area | Hosted (SIMULATED) | VM_MEASURED (QEMU 11.1.0, WHPX + TCG) |
|---|---|---|
| Judge | X001 cases both judges; J-series extended (C0/C9/C10/C11) | - |
| Memory / E04 | property + overlap + inconsistent-counter tests | `diag-map-overlap` |
| D-ABR-012 | H09-H12 again | collision-check, collision-alloc, double-release on final builds |
| Clock | clockguard unit tests | `diag-tsc-backward`, `diag-tsc-jump` |
| Lifecycle / events / faults | matrix, ring tests | normal boots C10; `diag-init-skip`; fault probes with context |
| Tools | label + window unit tests | diag_reset x2, timing probe x1 (TCG) |
| Regression | registry check (+ injected negative) | 0.31b positive W/T cold, R warm (TCG); 0.29 and 0.31a kernels under the new harness; repro; freeze, 0.29 and 0.31a checkpoint unchanged |

Not run: physical hardware, Secure Boot, ring 3, WHPX warm reset (still excluded, D-ABR-007), T01-T25.

## 9. Owner decisions requested

1. Approve this design for implementation.
2. Minimal events as a bounded log with no dispatch (section 5), or a minimal dispatch mechanism instead.
