# Patch notes: ABRAHAM 0.32 (kernel 0.32.0-dev)

For Jadin. 2026-11-06, MOSKO Laboratory 001 - Pripyat. Records TR-0036 (Steps 1-2) and TR-0037 (Steps 3-11).
**Status: 0.32 READY FOR AUDIT. Not accepted. Nothing advances to 0.33 without Echo's audit and your sign-off.**

## In one paragraph

Abraham now runs services. After the kernel says OPERATIONAL, it checks a fixed, compiled list of three entries
and starts them in dependency order:
- `svc.counter` counts its own small steps, and it reports RUNNING only after a probe step proves the count.
- `svc.netmon` honestly reports UNAVAILABLE / `NOT_INSTALLED`: it depends on `dev.net0`, a network adapter that does
  not exist yet. Nothing claims network monitoring.

Every status line uses only words from the ratified baseline (Appendix A for reasons), and keeps liveness and
compromise apart. It turns into UNKNOWN / `OBSERVATION_STALE` the moment the clock cannot be trusted.

I built and booted deliberately broken services, to prove that none of them can fake a success:
- one that fails its own check;
- one that lies about its work;
- one that is too slow;
- one that stalls for 6 seconds;
- a list with a dependency loop.

The 0.31b memory and clock guarantees were run again on the final builds, including your D-ABR-012 double-release
and collision tests, on both accelerators.

## Direct changes

| File | What changed | Why |
|---|---|---|
| `kernel/src/svcregistry.rs` (new) | The service list: exact names only (`svc.` / `dev.` + lowercase parts). Checked for duplicates, unknown or repeated dependencies, budgets and loops, at compile time and again at boot. Start order by dependency, ties by number. Lookup by exact bytes | Directive Step 3 |
| `kernel/src/svctable.rs` (new) | The production list (`dev.net0` not installed, `svc.counter`, `svc.netmon` depending on `dev.net0`) and the five DIAGNOSTIC lists. Every list except the deliberately looped one must pass the check, or the kernel does not build | Q1 |
| `kernel/src/svclife.rs` (new) | Six service states. Only 7 moves are allowed; 2 manual resets are reserved and nothing in the kernel can call them; everything else is refused with nothing changed | Step 4, Q2 |
| `kernel/src/svcrun.rs` (new) | The manager. No start before OPERATIONAL. Withheld while a dependency is not running. RUNNING only when the service's own check and the kernel's own count agree. One small step per service per timer tick. Time measured after the step returns (never called a timeout): 1 slow step makes it DEGRADED, 3 in a row FAILED. A failure stops what depends on it. Nothing restarts by itself | Steps 4-5 |
| `kernel/src/svcstatus.rs` (new) | The public status: a 9-row table, status / reason / liveness / compromise / time / clock. The reason type contains exactly the 27 Appendix A codes and cannot be made from text. Compromise cannot be set | Step 6, P-15, P-41, P-39 |
| `kernel/src/svc_counter.rs` (new) | `svc.counter`: one checked +1 per step; at the maximum it fails instead of wrapping | P-16 |
| `kernel/src/svcmgr.rs` (new) | The kernel side: one fixed manager, start right after the OPERATIONAL printout, one call in the main loop, status lines every 5 s, SERVICE events | Wiring |
| `kernel/src/svcdiag.rs` (new) | The broken services, compiled only into DIAGNOSTIC builds | Tests |
| `kernel/src/events.rs`, `eventlog.rs` | New event kind SERVICE. A read-only second printout of the records added after OPERATIONAL. Capacity (32), overwrite counting and numbering unchanged | Step 7, ABR-031-EVT-01 |
| `kernel/src/clock.rs` | A read-only "is the clock DEGRADED?" | Step 6 |
| `kernel/src/main.rs` | Starts the services after OPERATIONAL; one service call per loop; DIAGNOSTIC hooks | Wiring |
| `kernel/Cargo.toml`, `Cargo.lock` | Version 0.32.0-dev; five DIAGNOSTIC features | Version |
| `kernel/hosttest/` | The new modules compiled unchanged; 34 service tests; 4 new compile checks | Step 9 |
| `tools/abr_boot_001.py` | Profile 0.32: C0-C11 unchanged, plus C12 (21 service checks per boot). A status round cut off at the very end of a capture is tolerated and reported, nowhere else | Step 10 |
| `tools/g031/judge_selftest.py` | Accepts profile 0.32 | Re-run the 0.31a falsifications |
| `tools/g032/*` (new) | Start verification, copy, service probe, C12 self-test, code and reason checkers, static checks, mutation check, host-test recorder, campaign, supplement, index, package | Evidence |
| `docs/KERNEL_DIAGNOSTICS.md` | 65 new entries (217). Appendix A names are kept out of everything except `svcstatus.rs` | D-ABR-011/012 |
| `..\DECISIONS.md` | D-ABR-018 and D-ABR-019 appended (rows only) | Your decisions |

**Unchanged on purpose:**
- the memory allocator and its checks (`frame.rs`, `memory.rs`, `paging.rs`, `ptwalk.rs`);
- the boot lifecycle (`lifecycle.rs`, `init.rs`), the clock guard (`clockguard.rs`) and the fault path (`fault.rs`);
- `entry.asm` and the banner;
- `frozen\`, `work-0.29\`, `work-0.31\` and `work-0.31b\`, all re-verified at the end (I001, V001, V002).

## Evidence (all in `work-0.32\evidence`, every run sealed)

- **68 campaign entries: 67 behaved exactly as written down before they ran, 1 did not (J001, explained below).**
  - 23 of them have post-checks that read the evidence itself.
  - No source file changed during the campaign.
  - One supplementary entry after the campaign (J005) behaved as expected.
- **Normal boots** (WHPX and TCG, cold restart and TCG warm reset; 8 runs, 16 boots): all pass C0-C12.
  - `svc.counter` reached about 1,000 (WHPX) and 1,500 (TCG) in the 15 s window, always exactly its steps + 1.
  - `svc.netmon` and `dev.net0` were UNAVAILABLE / NOT_INSTALLED on every line.
  - Compromise was NONE_KNOWN on every line.
  - Nothing of the service manager appeared before the OPERATIONAL printout.
- **Broken services** (WHPX and TCG):
  - the loop in the list is refused at boot, and nothing starts (Y001/Y002);
  - a start before OPERATIONAL, an unknown name, a forbidden command and an illegal move are all refused, and the
    counter keeps going (Y003/Y004);
  - the honest failure and the liar both end FAILED, never RUNNING, and the service that depends on them is
    withheld (Y005/Y006);
  - the slow service overruns 3 times (20 ms each, against 1 ms) and is stopped, while the counter is unaffected
    (Y007/Y008).
- **The clock:** when the clock is made to jump back 2 s or forward 1 h, every later status of the counter says
  UNKNOWN / OBSERVATION_STALE with clock DEGRADED, while it keeps counting (Y009-Y012).
- **The 6 s stall (Y013, a limit, recorded as planned):**
  - the clock guard cannot tell a stalled step from a clock jump, so it reports a TSC jump and marks the clock
    DEGRADED;
  - this is the safe direction: nothing reads AVAILABLE afterwards;
  - the stalled service is stopped after 3.
- **D-ABR-012 repeated on the final builds:**
  - collision found by the check and by the allocation guard, and the boot stopped (N001-N004);
  - double release: pool unchanged, allocator FAULTED, stop (N005/N006);
  - on WHPX and TCG, and in none of these runs did a service start.
- **Old kernels under the new harness:**
  - the accepted 0.29, 0.31a and 0.31b binaries still pass their own profiles (G001-G003);
  - the 0.32 kernel passes the unchanged 0.31b profile (G004);
  - the 0.31b binary under the 0.32 profile fails on exactly C12, so C12 really tests something (G005).
- **The tests test something:**
  - 28 deliberate defects in the service code were each caught by a failing hosted test (H003);
  - all C12 falsifications fail for their own reason (J005, 42/42);
  - the 0.31a/0.31b falsifications still all fail (J002-J004).

## Failures and how they were handled

### Designed to fail (and they did, for the right reason)

- G005 (0.31b kernel, profile 0.32): fails C12 only; it has no services.
- N010 (QEMU killed): FAIL.
- N011 (no timer opt-out): CONTROL_NOT_QUALIFYING.
- N009 (wrong digest): refused, nothing run.
- N012 (tampered kernel): Limine refuses.
- K002, K003, P002: an unregistered code, a hand-written public reason and an extra reason are all caught.
- All the deliberate stops (N001-N008, F001-F005) and the broken services above.

### One unexpected result: J001 (my mistake in a test case, not in the kernel or the judge)

- **What happened:** the C12 self-test judged 41 doctored copies of a good run, and 40 were judged correctly. The
  one that came out wrong was a **control** that should pass: a copy that ends in the middle of a status round, the
  way the harness sometimes cuts a log when it stops QEMU.
- **Why:** I built that copy by cutting the log inside the last complete round and throwing away everything after
  it. That threw away heartbeats too, so the heartbeat condition (C5) failed. The service condition (C12) passed it,
  as intended. On my development run the same construction had happened to keep all heartbeats.
- **The real runs already show the rule working:** W001 and W002 both ended with a status round cut by the harness,
  and both were judged PASS, with the cut reported.
- **Fix:** the copy now keeps every line and adds a cut round at the end. I added a second control (a half-printed
  round).
- **Re-run:** recorded as J005 after the campaign closed, with its expectation written first: 42/42.
- J001 stays on record as unexpected. The supplement lists the one tool file I changed after close.

### My own mistakes found during development (none in a recorded run)

1. **A hosted test was weaker than it looked.** The mutation check found one deliberate defect that no test caught:
   a name rule that allows capital letters. The 9 bad names in the design all fail earlier, on their prefix. I
   added `svc.Counter` and `svc.a_b`; now all 28 defects are caught. The design's "9 malformed names" became 11.
2. **The new judge failed a correct development run** because the last status line of boot 2 was cut in half when
   the harness stopped QEMU. The tolerance rule above came from this. It is limited to the very end of a capture
   and tested both ways.
3. **A compiler warning in the first production build** (a helper only the hosted tests use). Marked like the other
   shared modules; the kernel's digest did not change.
4. **The 0.31a host-test recorder listed only `frame.rs` as its input.** The 0.32 copy lists every kernel source the
   hosted crate compiles.
5. **Tooling slips with no effect on any evidence:**
   - a shell quoting error stopped one registry edit before it ran;
   - I wrote a placeholder check into the draft index tool, and removed it before it was ever used;
   - I generated the source diff once before the documents were finished, deleted that copy (nothing referenced it)
     and regenerated it after them. Its console is kept, renamed `source_diff.early-discarded.console.txt`.

### Behaviors worth knowing (as designed, stated rather than hidden)

- The slow service showed AVAILABLE in its very first status line. Its readiness probe took 20 ms; the probe's time
  is reported but not judged. Its first real step overran 10 ms later.
- A service that lies consistently, in its state and its claims alike, cannot be caught by checks that read only
  that service. The kernel catches claims its state does not support. Nothing more is claimed.
- Failure rows (FAILED, withheld behind a failed dependency, overrun) print `reason=NONE`: Appendix A has no fitting
  code (your Q3 choice, B). The exact cause is on the diagnostic line next to it.

### Left unexplained

Nothing.

## Not claimed

- Acceptance.
- Hardware, Secure Boot, ring 3, SMP.
- WHPX warm reset (excluded, D-ABR-007); guest reboot (not implemented).
- Baseline tests T01-T25.
- Network monitoring of any kind.
- Any authority or enforcement by a service.
- Static checks are text and byte scans.
