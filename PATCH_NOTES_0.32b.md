# Patch notes: ABRAHAM 0.32b (kernel 0.32.1-dev)

For Jadin. 2026-11-08, MOSKO Laboratory 001 - Pripyat. Record TR-0038.
**Status: 0.32b READY FOR AUDIT. Not accepted. No launcher work; 0.33 waits for Echo's audit and your sign-off.**

## In one paragraph

The audit found four gaps in 0.32, and this patch closes exactly those four:
1. A service could take one more step after the service it depends on had stopped.
2. A step whose time could not be measured did not interrupt the run of good steps needed to recover.
3. The first, startup "probe" step was never timed, so a slow service could be called AVAILABLE.
4. The test checker C12 believed numbers that were impossible or contradicted each other.

Each one was first shown to be real on the unchanged 0.32 code, and that evidence is kept. Then it was fixed, and
shown fixed on the same tests, on both accelerators wherever a VM can show it. Everything else from 0.32 still
passes:
- the memory, clock and fault guarantees;
- the D-ABR-012 tests;
- the older kernels.

## Before you review: two things I could not settle myself

- **There is no audit document in the Abraham folder.** I worked from the four findings as written in your
  directive.
- **0.32 was never formally accepted.** No decision row accepts it, and TR-0037 says READY FOR AUDIT. I did not
  record an acceptance. I treated "0.32 acceptance evidence" as "the recorded 0.32 evidence", and left all of it
  untouched.

## The four corrections, plainly

| # | What was wrong | What changed | Where to see it |
|---|---|---|---|
| 1 | If service A failed in the middle of a cycle, a service B that depends on A still ran its step later in that same cycle | Before every step, the manager now checks that everything the service depends on is still RUNNING. If not, the service is stopped instead of stepped. | VM before: B did 3 steps against A's 2 (X003). After: 2 and 2 (Y014, Y015) |
| 2 | After a slow step, recovery needs 100 good steps in a row. A step whose time could not be measured did not break that run | An unmeasured step now resets the run of good steps | hosted tests (X001 failing, X005 passing; B05-B07). The VM cannot produce such a step |
| 3 | The startup probe's time was reported but not judged. A service with a 20 ms probe (20 times its budget) was shown AVAILABLE | The probe is judged like every step: a slow probe is the first slow step, so the service is DEGRADED, never AVAILABLE on it. The verdict is printed with readiness: `probe_timing=OVERRUN` | the kept 0.32 log fails the corrected check (X004); 0.32b: Y007/Y008 |
| 4 | C12 accepted a readiness count above the budget, a probe time of a full second, event times going backwards, status times that could not fit between the heartbeats, and start lines in the wrong order | C12 checks 7 more things: counts possible, durations consistent, states consistent with their own history. The service probe checks the same | the old checker passed 10 of 10 doctored logs (X002); the new one rejects all of them (X006, X007) and changes no genuine result (Q001: 16 of 16 old runs unchanged) |

**One reading for you to confirm.** Your design said one slow step makes a service DEGRADED and three in a row make
it FAILED. I applied exactly that rule to the probe. So a service with a slow probe still starts, but it is
DEGRADED, and two more slow steps stop it. The stricter alternative, refusing to start a service whose probe was
slow, is a one-place change if you prefer it.

## Direct changes

| File | What changed | Why |
|---|---|---|
| `kernel/src/svcrun.rs` | the dependency check before each step (`deps_running`); one shared time-accounting function used for the probe and every step (`account`); an unmeasured step resets the good-step run; the probe verdict (`StepTiming`) | Findings 1-3 |
| `kernel/src/svcmgr.rs` | the readiness line ends with `probe_timing=...` | Finding 3 |
| `kernel/src/svctable.rs`, `svcdiag.rs`, `main.rs`, `Cargo.toml`, `Cargo.lock` | a DIAGNOSTIC cascade table and its two test services; version 0.32.1-dev | Finding 1 on the VM |
| `kernel/hosttest/` | `repro_0_32_findings.rs` (the four tests, failing before and passing after); `services_032b_tests.rs` (13 tests including healthy negative controls); one 0.32 test corrected (it had asserted the defect) | Hosted evidence |
| `tools/abr_boot_001.py` | hardened C12 (21 to 28 items); profile 0.32b | Finding 4 |
| `tools/g032/service_probe.py` | corrected expectations; cascade mode; the same hardened checks; can re-judge any old log | Findings 1, 3, 4 |
| `tools/g032/static_checks_032.py`, `verify_tree_checkpoint.py`, `tools/g031/judge_selftest.py` | the new diagnostic names and table; work-0.32 as a protected tree; profile 0.32b | Checks |
| `tools/g032b/*` (new) | start verification, copy, reproduction, re-judging, the 58-case self-test, the 35-mutant check, campaign, packaging | Evidence |
| `docs/KERNEL_DIAGNOSTICS.md` | 4 new entries (`SVC_DIAG_INJECTED_STEP_ERROR`, `IN_BUDGET`, `OVERRUN`, `UNMEASURED`): 221 registered, up from 217 | Registry |
| `..\DECISIONS.md` | D-ABR-020 appended | Your directive |

**Not changed:**
- the registry rules, the lifecycle, the status mapping;
- memory, clock, faults, `entry.asm`;
- `work-0.32` and every older tree, all re-verified (V001-V003, I001).

## Evidence

- **Reproduced before correcting:** X001 (4 hosted tests fail), X002 (10 doctored logs pass the old checker), X003
  (the cascade on the VM), X004 (the old slow-service log).
- **Campaign:** 77 entries, all 77 as written down beforehand (28 with evidence post-checks). No source file changed
  during it.
- **Counted boots:** C0-C12 pass on 16 boots (WHPX and TCG, cold and TCG warm). The counter's probe is
  `probe_timing=IN_BUDGET`.
- **D-ABR-012:** collision and double release stop the kernel on both accelerators (N001-N006). No service starts
  in any of those runs.
- **Older kernels:** the 0.29, 0.31a and 0.31b binaries pass their profiles (G001-G003). The 0.32 kernel still
  passes its own (G006). Under 0.32b it fails only for the missing `probe_timing` claim (G007), as expected.
- **The tests test something:** 35 of 35 deliberate defects caught (H003); 58 of 58 doctored logs rejected for their
  own reason (J001).

## Failures and how they were handled

### Designed to fail (and they did, for the right reason)

- X001-X004: the defects themselves, reproduced.
- G005: the 0.31b kernel, which has no services.
- G007: the 0.32 kernel, with the new readiness line missing.
- N009-N012: wrong digest, killed QEMU, no timer fix, tampered kernel.
- K002, K003, P002.
- All the deliberate stops and broken services.

### My own mistakes found during development (none in a recorded run)

1. **I first fixed finding 1 twice over:** an immediate stop after a failure, plus a check before each step. Either
   one alone fixes it, and with both present no test could fail if one were removed, which made both untestable. I
   kept only the check before each step. The mutation check now proves it matters (M29, M30).
2. **One of my new tests was wrong:** it expected the start-up reports without the registry line. I fixed the test,
   not the code.
3. **The same shell quoting error as in 0.32** stopped one script before it ran. I wrote it to a file instead.
4. **A stray command** of mine ran the start verifier with `/dev/null` as its output paths. On Windows that resolves
   to `C:\dev\null`, which does not exist, so nothing was written.
5. **A copied docstring** in `branch_from_032.py` still says "its work-0.31b source" on one line, where it should
   say work-0.32. The tool itself uses work-0.32, as its recorded output shows. I left the text as it was run.
6. **During packaging, I wrote the source diff before creating its folder** (the 0.31 lesson again). Nothing was
   written; the failed console is kept (`source_diff.failed-no-folder.console.txt`). Then this note was added, and
   the diff was written once more, so that it includes this note.

### Left unexplained

Nothing.

## Not claimed

- Acceptance of 0.32 or 0.32b.
- Echo's audit text.
- Hardware, Secure Boot, ring 3, SMP.
- WHPX warm reset; guest reboot.
- T01-T25.
- Any network capability or authority.
- Detecting a service that lies consistently.
- Preemption or timeouts.
